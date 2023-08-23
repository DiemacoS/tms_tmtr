from odoo import api, fields, models, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class TmtrExchangeOneCPurchaseOrder(models.Model):
    _name = 'tmtr.exchange.1c.purchase.order'
    _description = '1C Deliver Order'

    ref_key = fields.Char(string='Ref key') # ref_key order
    date_car_out = fields.Char(string='Departure date of the car')  # Дата выезда машины
    is_load = fields.Boolean(string='The order has been shipped')  # Был ли отправлен заказ
    date = fields.Char(string='Date') #Дата создания в 1с
    responsible_key = fields.Char(string='Responsible key') #ref_key ответственного
    store_key = fields.Char(string='Warehouse key')  # Склад key
    number = fields.Char(string='Number') #Номер заказа
    note = fields.Char(string='Note') #Заметки

    route_ids = fields.One2many('tmtr.exchange.1c.route', 'order_id', string='Routes')
    impl_ids = fields.One2many('tmtr.exchange.1c.implemention', 'order_id', string='Implementions')

    def _create_delivery(self, json_value, route_tms, driver_id):
        return self.env['tms.delivery'].create({
            'route_id': route_tms[0].id,
            'name': json_value['Number'],
            'order_num': json_value['Number'],
            'car_departure_date': datetime.strptime(json_value['ДатаВыездаМашины'], '%Y-%m-%dT%H:%M:%S'),
            'notes': json_value['Примичание'],
            'date_create_1c': self._parse_date(json_value['Date']),
            'carrier_driver_id': driver_id,
        })

    def _create_returns_delivery(self, impl_json_value, tms_delivery, name_client):
        return self.env['tms.delivery.row'].create({
            'delivery_id': tms_delivery.id,
            'order_row_type': 'return',
            'notes': impl_json_value['Комментарий'],
            'client_name': name_client,
            'impl_num': "Возврат {number}".format(number=impl_json_value['LineNumber']),
            'comment': "{phone};{address}".format(phone='-', address=impl_json_value['Адрес']),
        })

    def _create_delivery_row(self, impl_json_value, tms_delivery, name_client):
        return self.env['tms.delivery.row'].create({
            'delivery_id': tms_delivery.id,
            'order_row_type': 'delivery',
            'selected_1c': impl_json_value['Выбрать'],
            'impl_num': impl_json_value['Номер'],
            'notes': impl_json_value['Комментарий'],
            'client_name': name_client,
            'comment': "{phone};{address}".format(
                phone=impl_json_value['Телефон'].replace(";", ""),
                address=impl_json_value['АдресДоставки'].replace(";", "")
            ),
        })

    def _get_p_order_on_stock_key(self, date, stock_key, top, skip):
        date = date.strftime("%Y-%m-%dT00:00:00")
        return self.env['odata.1c.route'].get_by_route(
            "1c_ut/get_p_order_on_stock_key/",
            {
                "date": date,
                "stock_key": stock_key,
                "top": top,
                "skip": skip
            }
        )['value']

    def _get_unique_values_on_filed(self, objects, name_field):
        return list(set(obj[name_field] for obj in objects))

    def _update_carrier_id(self, obj, tk_keys):
        obj.carrier_id = tk_keys[0] if tk_keys else obj.carrier_id
        return obj

    def _get_transport_company_ids(self, tk_keys):
        transport_companies = self.env['tmtr.exchange.1c.transport.company'].search([
            ('ref_key', 'in', tk_keys),
            ('carrier_id', '!=', None)
        ], limit=1)
        return transport_companies.mapped('carrier_id.id')

    def _parse_date(self, str_date):
        date = datetime.strptime(str_date, '%Y-%m-%dT%H:%M:%S')
        return date - timedelta(hours=3)  # Время по мск

    def _upload_purchase_order(self, purchases_data):

        count_order = 0

        clients = self.env['tmtr.exchange.1c.counterparty'].search([])
        cash_clients = {client.ref_key: client.full_name for client in clients}

        delivery_records = self.env['tms.delivery'].search([])
        delivery_dict = {(delivery.order_num, delivery.date_create_1c): delivery for delivery in delivery_records}

        for purchase_data in purchases_data:

            routes = self.env['tms.route'].upload_new_route(purchase_data)

            driver = self.env['tms.carrier.driver'].get_carrier_driver(
                purchase_data['Водитель_Key']
            )  # выгрузка водителей

            self.env['tmtr.exchange.1c.company.route'].create_company_route(purchase_data)

            order_number = purchase_data['Number']
            date_create_1c = purchase_data['Date']

            delivery_tms = delivery_dict.get((order_number, date_create_1c), None)

            if not delivery_tms:
                delivery_tms = self._create_delivery(purchase_data, routes, driver.id if driver else False)
                count_order += 1
            else:
                continue

            tk_unique_keys = self._get_unique_values_on_filed(purchase_data['Реализации'], 'ТК')

            carrier_ids = self._get_transport_company_ids(tk_unique_keys)

            delivery_tms.carrier_id = carrier_ids[0] if carrier_ids else False

            for item in tk_unique_keys:
                self.update_intervals(delivery_tms, routes, item)  # выгрузка интервалов

            if not delivery_tms.delivery_row_ids:
                if purchase_data['Реализации']:
                    for item in purchase_data['Реализации']:
                        name_client = cash_clients.get(item['Контрагент_Key'])
                        self._create_delivery_row(item, delivery_tms, name_client=name_client)
                if purchase_data['ДопУслуги']:
                    for item in purchase_data['ДопУслуги']:
                        name_client = item['Контрагент']
                        self._create_returns_delivery(item, delivery_tms, name_client=name_client)

        return count_order

    def _get_route_upload_date(self):
        return fields.Date.to_date(
            self.env['ir.config_parameter'].sudo().get_param(
                'tmtr.exchange.1c_purchase_order_date',
                '2023-07-11'
            )
        )

    def upload_deliveries(self, route_upload_date=None, top=50, skip=0):
        """Выгружает заказы из 1с в tms.delivery и tms.delivery_row"""

        incomplete_stocks_json_str = self.env['ir.config_parameter'].get_param(
            'tmtr.exchange.1c_stock_not_upload'
        )  # Склады, которе не успели выгрузится

        if incomplete_stocks_json_str:  # Если есть невыгруженные склады

            incomplete_stocks_json = json.loads(incomplete_stocks_json_str.replace("'", "\""))

            date = datetime.strptime(incomplete_stocks_json.get("date"), '%Y-%m-%d').date()

            stock_ref_keys = incomplete_stocks_json.get('stock_1c_key', [])

            if not stock_ref_keys:
                return

            finish_before = datetime.now() + timedelta(minutes=1)  # ограничить время работы скрипта одной минутой
            total_cnt = 0
            index = 0

            while datetime.now() < finish_before and index < len(stock_ref_keys):

                purchases_data = self._get_p_order_on_stock_key(
                    date=date,
                    stock_key=stock_ref_keys[index],
                    top=top,
                    skip=skip
                )

                if purchases_data:
                    skip += top
                    total_cnt += self.upload_purchase_order(purchases_data)
                else:
                    index += 1
                    skip = 0

            incomplete_stocks_json = {
                'stock_1c_key': stock_ref_keys[index:],
                'date': date
            } if stock_ref_keys[index:] else None

            self.env['ir.config_parameter'].set_param('tmtr.exchange.1c_stock_not_upload', incomplete_stocks_json)

            return {
                'Тип': 'Загрузка невыгруженных',
                'Количество заказов': total_cnt,
                'Не полностью выгруженные склады за итерацию': incomplete_stocks_json,
            }

        else:
            if not route_upload_date:
                route_upload_date = self._get_route_upload_date()
                # if(type(route_upload_date) == str):
                #     route_upload_date =  datetime.strptime

            date = route_upload_date

            stock_ref_keys_records = self.env['tms.route'].search([
                "&", ("name", "=", 'upload'), "&", ("start_time", "=", None),
                "&", ("end_time", "=", None), "&", ("stock_id", "!=", None),
                "&", ("route_1c_key", "=", None), ("stock_1c_key", "!=", None)
            ])

            stock_ref_keys = stock_ref_keys_records.mapped('stock_1c_key')

            if not stock_ref_keys:
                return

            finish_before = datetime.now() + timedelta(minutes=1)  # ограничить время работы скрипта одной минутой
            date_till = datetime.now().date()  # не искать дальше текущей даты
            total_count_order = 0
            stock_index = 0

            while datetime.now() < finish_before:
                if stock_index >= len(stock_ref_keys):  # Если всё выгрузили
                    if date >= date_till:
                        break
                    date += timedelta(days=1)
                    stock_index = 0
                    skip = 0

                purchases_data = self._get_p_order_on_stock_key(
                    date=date,
                    stock_key=stock_ref_keys[stock_index],
                    top=top,
                    skip=skip
                )

                if purchases_data:
                    skip += top
                    total_count_order += self._upload_purchase_order(purchases_data)
                else:
                    stock_index += 1
                    skip = 0

            incomplete_stocks_json = {
                'stock_1c_key': stock_ref_keys[stock_index:],
                'date': date.strftime('%Y-%m-%d')
            } if stock_ref_keys[stock_index:] else None

            self.env['ir.config_parameter'].set_param(
                'tmtr.exchange.1c_stock_not_upload',
                incomplete_stocks_json
            )

            if date <= date_till:
                self.env['ir.config_parameter'].sudo().set_param(
                    'tmtr.exchange.1c_purchase_order_date',
                    date.strftime('%Y-%m-%d')
                )

            return {
                'Тип': 'Новая загрузка',
                'Количество заказов': total_count_order,
                'Не полностью выгруженные склады': stock_ref_keys[stock_index:],
            }

    def update_intervals(self, delivery_tms, routes, tc_key):
        """Обновляет интервалы в tms.delivery"""

        if not routes:
            return

        value = self.env['tmtr.exchange.1c.intervals'].get_intervals(
            routes[0].route_1c_key,
            routes[0].stock_1c_key,
            tc_key
        )

        if not value:
            return

        delivery_date = delivery_tms.car_departure_date or delivery_tms.date_create_1c
        delivery_terms = int(value.delivery_terms)
        date = delivery_date + timedelta(days=delivery_terms)

        interval_from = datetime(
            date.year,
            date.month,
            date.day,
            value.interval_from.hour,
            value.interval_from.minute,
            0)

        interval_to = datetime(
            date.year,
            date.month,
            date.day,
            value.interval_to.hour,
            value.interval_to.minute,
            0)

        delivery_tms.update({
            'interval_from': interval_from,
            'interval_to': interval_to,
        })