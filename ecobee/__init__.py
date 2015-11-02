
__author__ = 'Michael Stella <ecobee@thismetalsky.org>'

import datetime
import json
import logging
import requests
import os
import shelve

APIVERSION = '1'
REPORT_COLUMNS = (
    'auxHeat1', 'auxHeat2', 'auxHeat3',
    'compCool1', 'compCool2', 'compHeat1', 'compHeat2',
    'dehumidifier', 'dmOffset', 'economizer', 'fan', 'humidifier',
    'outdoorHumidity', 'outdoorTemp', 'sky', 'ventilator', 'wind',
    'zoneAveTemp', 'zoneCalendarEvent', 'zoneCoolTemp', 'zoneHeatTemp',
    'zoneHumidity', 'zoneHumidityHigh', 'zoneHumidityLow', 'zoneHvacMode', 'zoneOccupancy'
)


class EcobeeException(Exception):
    """Ecobee error"""
    pass


class Ecobee(object):
    """Ecobee thermostat.

       eapi = Ecobee(apikey, themostat_ids)

    """
    def __init__(self, apikey, thermostat_ids, scope='smartWrite', authfile=None):
        """
          apikey:         your API key in the 'Developer' panel on ecobee.com
          thermostat_ids: IDs of your thermostats
          authfile:       Store authentication in this file.
                          Default=$HOME/.config/ecobee
          scope:          Default: smartWrite

        """

        self.log = logging.getLogger(__name__)
        self.scope = scope
        self.apikey = apikey
        if isinstance(thermostat_ids, list):
            self.thermostat_ids = thermostat_ids
        else:
            self.thermostat_ids = [thermostat_ids]

        # make sure we have strings here
        self.thermostat_ids = list(str(tid) for tid in self.thermostat_ids)

        self.url_base = 'https://api.ecobee.com/'
        self.url_api = self.url_base + APIVERSION + '/{endpoint}'


        # Map of thermostat ID to the last revision seen.
        self.lastSeen = {}

        # Map of most recent data
        self.data = {}
        for tid in self.thermostat_ids:
            self.data[tid] = {}

        # setup authentication storage
        self.auth = {}
        if authfile:
            self.auth = shelve.open(authfile)
        else:
            self.auth = shelve.open(os.path.join(os.getenv('HOME'), '.config', 'ecobee'))

        # authorize on start
        self.authorize_refresh()


    @property
    def authentication_required(self):
        return self.auth.get('required', True)


    def authorize_start(self):
        """Setup authorization - this will prompt the user to go to
        the ecobee website and create the authorized application.

        Be sure to call ecobee.authorize_finish() when done.
        """
        self.auth['required'] = True

        if self.auth.get('refresh_token'):
            self.log.debug("Already authorized.")
            return

        # a previous auth was in progress
        if self.auth.get('token_type') == 'authorize':
            self.log.debug("Waiting for user to authorize application.")
            return self.authorize_finish()

        self.log.info("Starting authorization")
        response = self._raw_get("authorize", response_type='ecobeePin', client_id=self.apikey, scope=self.scope)
        if not response.ok:
            self.log.error(response.text)
            return

        result = response.json()
        self.auth['access_token'] = result['code']
        self.auth['token_type'] = 'authorize'
        self.auth['expiration'] = datetime.datetime.now() + datetime.timedelta(minutes=int(result['expires_in']))
        self.auth['refresh_token'] = None

        self.log.info("""Please log onto the ecobee web portal, log in, select the menu
in the top right (3 lines), and select MY APPS.
Next, click Add Application and enter the following
authorization code: {pin}
Then follow the prompts to add your application.
You have {expiry} minutes.
""".format(pin=result['ecobeePin'], expiry=result['expires_in']))


    def authorize_finish(self):
        """Finish authorization after the user has allowed access
        at the Ecobee website."""

        if not self.auth.get('access_token'):
            self.log.info("No access token, can't finish?")
            return

        # hah, timed out, try again.
        if datetime.datetime.now() > self.auth['expiration']:
            self.auth['access_token'] = None
            return self.authorize_start()

        self.log.info("Finalizing authorization")
        response = self._raw_post('token',
                                  grant_type = 'ecobeePin',
                                  code       = self.auth['access_token'],
                                  client_id  = self.apikey)

        self._authorize_update(response)


    def authorize_refresh(self, force=True):
        """Refresh authorization"""

        # no refresh token means we go authorize
        if not self.auth.get('refresh_token'):
            self.log.info("No refresh token, authorizing.")
            return self.authorize_start()

        # don't refresh if not yet expired
        if 'expiration' in self.auth and self.auth['expiration'] > datetime.datetime.now():
            return

        self.log.info("refreshing authorization")
        response = self._raw_post('token',
                                  grant_type = 'refresh_token',
                                  code       = self.auth['refresh_token'],
                                  client_id  = self.apikey)
        self._authorize_update(response)


    def _authorize_update(self, response):
        """Update cached authentication"""

        if not response.ok:
            result = response.json()
            self.log.error(result['error_description'])
            return

        result = response.json()

        self.auth["access_token"]  = result["access_token"]
        self.auth["token_type"]    = result["token_type"]
        self.auth["refresh_token"] = result["refresh_token"]
        self.auth["expiration"]    = datetime.datetime.now() + datetime.timedelta(minutes=int(result["expires_in"]))
        self.auth["required"]      = False


    def thermostatSummary(self):
        """ /thermostatSummary
        Summary of available thermostats"""

        return self.get("thermostatSummary", {
                            "selection": {
                                "selectionType": "registered",
                                "selectionMatch": "",
                            }
                        })


    def thermostat(self, includeDevice=False, includeProgram=False, includeRuntime=False, includeEvents=False, includeEquipmentStatus=False, includeSensors=False):
        """ /thermostat
        Return info about the thermostat."""

        data = self.get("thermostat", {
            "selection": {
                "selectionType":  "thermostats",
                "selectionMatch": ":".join(self.thermostat_ids),
                "includeDevice":  includeDevice,
                "includeProgram": includeProgram,
                "includeRuntime": includeRuntime,
                "includeEvents":  includeEvents,
                'includeSensors': includeSensors,
                "includeEquipmentStatus": includeEquipmentStatus,
            }
        })
        return {thermostat['identifier']: thermostat for thermostat in data['thermostatList']}


    def runtimeReport(self, start_date=None, includeSensors=False, columns=REPORT_COLUMNS):
        """ /runtimeReport
        start_date defaults to 1 day ago.

        Date/time is in thermostat time,  Temps are in Fahrenheit.

        NOTE: This request should not be made at an interval of less than
        15 minutes as the data on the server only changes every 15 minutes

        OUTPUT line format:
           startDate
           startInterval
           endDate
           endInterval
           columns
           reportList
           sensorList

        """
        end_date = datetime.date.today()
        if not start_date:
            start_date = end_date - datetime.timedelta(days=1)
        data = {
            'startDate':      start_date.strftime('%Y-%m-%d'),
            'endDate':        end_date.strftime('%Y-%m-%d'),
            'columns':        ','.join(columns),
            'includeSensors': includeSensors,
            'selection': {
                "selectionType":  "thermostats",
                "selectionMatch": ":".join(self.thermostat_ids),
            }
        }
        return self.get('runtimeReport', data)


    def poll(self):
        """
        Return a list of thermostat IDs that have been updated since the last poll.
        https://www.ecobee.com/home/developer/api/documentation/v1/operations/get-thermostat-summary.shtml

        * NOTE:
            DO NOT poll at an interval quicker than once every 3 minutes,
            which is the shortest interval at which data might change.
        """
        summary = self.thermostatSummary()
        updated = []
        if 'revisionList' not in summary:
            self.log.warn("Couldn't find revisionList in the summary output")
            return []

        for revision in summary['revisionList']:
            parts = revision.split(":")
            identifier = parts[0]
            intervalRevision = parts[6]
            if intervalRevision != self.lastSeen.get(identifier):
                updated.append(identifier)
                self.lastSeen[identifier] = intervalRevision
        return updated


    @property
    def _headers(self):
        return {
            'Content-Type': 'application/json;charset=UTF-8',
            'Authorization': '{} {}'.format(self.auth['token_type'], self.auth['access_token']),
        }


    def get(self, endpoint, data):
        """Ecobee API-specific wrapper for requests.get"""
        self.authorize_refresh()

        url = self.url_api.format(endpoint=endpoint)
        r = requests.get(url, params = {'json': json.dumps(data)}, headers=self._headers)
        if not r.ok:
            self._handle_error(r)
        else:
            return r.json()


    def post(self, endpoint, data):
        """Ecobee API-specific wrapper for requests.post"""
        self.authorize_refresh()

        url = self.url_api.format(endpoint=endpoint)
        r = requests.get(url, data = json.dumps(data), headers=self._headers)

        if not r.ok:
            self._handle_error(r)
        else:
            return r.json()


    def _handle_error(self, response):
        self.log.debug(response.text)
        try:
            data = response.json()
            # code 16 = auth revoked, clear the token and start again
            if data['status']['code'] == 16:
                self.auth['refresh_token'] = None
                self.auth['token_type'] = None
                return self.authorize_start()

            # otherwise just raise it
            raise EcobeeException('{}: {}'.format(data['status']['code'], data['status']['message']))

        # failed to parse the JSON so this must be bad
        except ValueError:
            raise (response.text)


    def _raw_get(self, endpoint, **kwargs):
        """Mostly-raw GET used for authentication API"""
        h = {'Content-Type': 'application/json;charset=UTF-8'}
        url = self.url_base + endpoint
        return requests.get(url, params=kwargs, headers=h)


    def _raw_post(self, endpoint, **kwargs):
        """Mostly-raw POST used for authentication API"""
        h = {'Content-Type': 'application/json;charset=UTF-8'}
        url = self.url_base + endpoint
        return requests.post(url, params=kwargs, headers=h)
