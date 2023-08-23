from odoo import api, fields, models, _
import uuid

class TmsDriverBrowser(models.Model):
    _name = "tms.driver.browser"
    _description = 'Driver browser'

    unique_key = fields.Char(string='Unique_key', required=True)
    user_id = fields.Many2one('res.users')

    def set_unique_key(self, user_id):
        new_browse_uid = self.create_driver_browser(user_id)
        return new_browse_uid
    
    @api.model
    def get_unique_key_on_user_id(self, user_id, browse_key):
        data_browse = self.env['tms.driver.browser'].search([('unique_key', '=', browse_key)], limit=1)

        if not data_browse:
            new_browse = self.set_unique_key(user_id=user_id)
            result = new_browse
        else:
            result = data_browse

        return {
            'id': result['id'],
            'browse_uid': result['unique_key']
        }
    
    def create_driver_browser(self, user_id):
        return self.create({
            'unique_key': uuid.uuid1(),
            'user_id': user_id,
        })
