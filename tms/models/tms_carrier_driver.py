from odoo import api, fields, models, _


class TmsCarrierDriver(models.Model):
    _name = "tms.carrier.driver"
    _description = 'Carrier driver'

    name = fields.Char(string='Name', required=True)
    user_id = fields.Many2one('res.users', string='Driver id')