import requests
from webargs.flaskparser import use_kwargs
from app import Root
from ..assets.error_handling import *
from ..requests.status_request import status_args
from .common import CommonResoures

resource = CommonResoures()

class FullStatus():

    @use_kwargs(status_args)
    def get(self, imei, seen_with):
        try:
            response = {}
            tac = imei[:8] # slice TAC from IMEI
            if tac.isdigit(): # TAC format validation
                tac_response = requests.get('{}/coreapi/api/v1/tac/{}'.format(Root, tac)).json() # dirbs core TAC api call
                imei_response = requests.get('{}/coreapi/api/v1/imei/{}?include_seen_with={}'.format(Root, imei, seen_with)).json() # dirbs core IMEI api call with seen with information
                full_status = dict(tac_response, **imei_response)
                if full_status['gsma']: # TAC verification
                    response['imei'] = full_status['imei_norm']
                    response['brand'] = full_status['gsma']['brand_name']
                    response['model_name'] = full_status['gsma']['model_name']
                    response['model_number'] = full_status['gsma']['marketing_name']
                    response['device_type'] = full_status['gsma']['device_type']
                    response['manufacturer'] = full_status['gsma']['manufacturer']
                    response['operating_system'] = full_status['gsma']['operating_system']
                    response['radio_access_technology'] = full_status['gsma']['bands']
                    response['classification_state'] = full_status['classification_state']
                    if seen_with==1:
                        response['associated_msisdn'] = full_status['seen_with']
                    blocking_conditions = full_status['classification_state']['blocking_conditions']
                    complain_status = resource.get_complaince_status(blocking_conditions, full_status['seen_with']) # get compliance status
                    response = dict(response, **complain_status) if complain_status else response
                    return Response(json.dumps(response), status=200, mimetype='application/json')
                else:
                    return custom_response("IMEI not found", 404, 'application/json')
            else:
                return custom_response("Bad TAC format", 400, 'application/json')
        except Exception as e:
            print(e)