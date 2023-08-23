from odoo import api, fields, models, _

class TmsCarrierRoute(models.Model):
    _name = "tms.carrier.route"
    _description = 'Carrier route'

    name = fields.Char(string='Name', required=True)

    carrier_id = fields.Many2one('tms.carrier', string='Carrier id')
    driver_id = fields.Many2one('tms.carrier.driver', string='Carrier driver id')
    route_id = fields.Many2one('tms.route', string='Route id')
    is_consolidated_cargo = fields.Boolean(string="Is consolidated cargo")

    def create_carrier_route(self, carrier_id, carrier_name, route_ids):
        "Создать связь между тк и маршрутом"

        carrier = self.search([('carrier_id', '=', carrier_id)])

        if not carrier:
            values_to_create = [{
                'name': carrier_name,
                'carrier_id': carrier_id,
                'route_id': item
            } for item in route_ids]
            self.create(values_to_create)
        else:
            existing_route_ids = carrier.route_id.ids

            route_ids_to_create = list(set(route_ids) - set(existing_route_ids))

            values_to_create = [{
                'name': carrier_name,
                'carrier_id': carrier_id,
                'route_id': item
            } for item in route_ids_to_create]

            self.create(values_to_create)

