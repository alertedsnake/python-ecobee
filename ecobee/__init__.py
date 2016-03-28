# vim: set fileencoding=utf-8
"""
A simple library to talk to an Ecobee (https://www.ecobee.com) thermostat.
"""

__author__ = 'Michael Stella <ecobee@thismetalsky.org>'

import datetime
import json
import logging
import requests
import os
import shelve

from ecobee.objects import Thermostat

APIVERSION = '1'
REPORT_COLUMNS = (
    'auxHeat1', 'auxHeat2', 'auxHeat3',
    'compCool1', 'compCool2', 'compHeat1', 'compHeat2',
    'dehumidifier', 'dmOffset', 'economizer', 'fan', 'humidifier',
    'outdoorHumidity', 'outdoorTemp', 'sky', 'ventilator', 'wind',
    'zoneAveTemp', 'zoneCalendarEvent', 'zoneCoolTemp', 'zoneHeatTemp',
    'zoneHumidity', 'zoneHumidityHigh', 'zoneHumidityLow', 'zoneHvacMode', 'zoneOccupancy'
)

STATUS_SECTIONS = ('device', 'equipmentStatus', 'events', 'runtime',
                   'remoteSensors', 'program', 'settings',
)
UNITS_F = '°F'
UNITS_C = '°C'


class EcobeeException(Exception):
    """Ecobee error"""
    pass


class Client(object):
    """Ecobee thermostat.

       eapi = ecobee.Client(apikey, themostat_ids)

    """
    def __init__(self, apikey, scope='smartWrite', thermostat_ids=None, authfile=None, authstore=None):
        """
          apikey:         your API key in the 'Developer' panel on ecobee.com
          scope:          Default: smartWrite
          thermostat_ids: IDs of your thermostats, otherwise discover
          authfile:       Store authentication in this shelve file.
                          Default=$HOME/.config/ecobee
          authstore:      Provide your own dict-like authentication cache store

        """

        self.log = logging.getLogger(__name__)
        self.scope = scope
        self.apikey = apikey
        self.thermostat_ids = []

        # Map of most recent data
        self._status = {}

        if thermostat_ids:
            if isinstance(thermostat_ids, list):
                self.thermostat_ids = thermostat_ids
            else:
                self.thermostat_ids = [thermostat_ids]

            # make sure we have strings here
            self.thermostat_ids = list(str(tid) for tid in self.thermostat_ids)

            # setup the stats
            for tid in self.thermostat_ids:
                self._status[tid] = {}

        self.url_base = 'https://api.ecobee.com/'
        self.url_api = self.url_base + APIVERSION + '/{endpoint}'

        # Map of thermostat ID to the last revision seen.
        self.lastSeen = {}

        # setup authentication storage
        self.auth = {}
        # use provided authentiation
        if authstore:
            self.auth = authstore
        # use shelve - this is not thread safe!
        else:
            if authfile:
                self.auth = shelve.open(authfile)
            else:
                self.auth = shelve.open(os.path.join(os.getenv('HOME'), '.config', 'ecobee'))

        # authorize on start
        self.authorize_refresh(force=True)


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


    def authorize_refresh(self, force=False):
        """Refresh authorization"""

        # no refresh token means we go authorize
        if not self.auth.get('refresh_token'):
            self.log.info("No refresh token, authorizing.")
            self.auth.token_type = None
            return self.authorize_start()

        # don't refresh if not yet expired
        if not force and ('expiration' in self.auth and
                          self.auth['expiration'] > datetime.datetime.now()):
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
        """Summary of available thermostats.  Calls API endpoint /thermostatSummary """

        data = self.get("thermostatSummary", {
                            "selection": {
                                "selectionType": "registered",
                                "selectionMatch": "",
                            }
                        })

        # might not have got a useful response,
        # like when we have to refresh authentication
        if not data:
            return

        # go through the returned thermostat IDs and add
        # to the list we've cached if we haven't seen
        # them before
        for row in data['revisionList']:
            tid = row.split(':', 1)[0]
            if tid not in self.thermostat_ids:
                self.thermostat_ids.append(tid)
                self._status[tid] = {}

        return data


    def update(self, thermostat_ids=None, includeProgram=False, includeEvents=False):
        """Update cached info about the thermostats.  Calls API endpoint /thermostat """

        # none specified, use them all
        if not thermostat_ids:
            # no ids means we have to go fetch them
            if not self.thermostat_ids:
                self.thermostatSummary()
            thermostat_ids = self.thermostat_ids

        elif not isinstance(thermostat_ids, list):
            thermostat_ids = [thermostat_ids]

        self.log.info("Updating IDs {}".format(thermostat_ids))

        data = self.get("thermostat", {
            "selection": {
                "selectionType":  "thermostats",
                "selectionMatch": ":".join(thermostat_ids),
                "includeEquipmentStatus":   True,
                "includeDevice":            True,
                "includeSettings":          True,
                "includeRuntime":           True,
                'includeSensors':           True,
                "includeProgram":           includeProgram,
                "includeEvents":            includeEvents,
            }
        })
        for thermostat in data['thermostatList']:

            # remap the sensors as a dict
            sensors = {}
            for sensor in thermostat['remoteSensors']:
                sensors[sensor['id']] = sensor
            thermostat['remoteSensors'] = sensors

            # store it
            self._status[thermostat['identifier']] = thermostat


    def runtimeReport(self, thermostat_ids=None, start_date=None, includeSensors=False, columns=[]):
        """ Get a full runtime report. Calls API endpoint /runtimeReport

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
        if not columns:
            columns = REPORT_COLUMNS

        if not thermostat_ids:
            thermostat_ids = self.thermostat_ids

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
                "selectionMatch": ":".join(thermostat_ids),
            }
        }
        return self.get('runtimeReport', data)


    def resumeProgram(self, thermostat_id):
        """Resumes the program"""

        return self.post('thermostat', {
            "selection": {
                "selectionType":  "thermostats",
                "selectionMatch": thermostat_id,
            },
            "functions": [{
                "type": "resumeProgram",
                "params": {
                    "resumeAll": True,
                }
            }]
        })


    def setHold(self, thermostat_id, holdType='nextTransition', holdClimateRef=None,
                heatHoldTemp=None, coolHoldTemp=None, holdHours=None,
                startDate=None, endDate=None, startTime=None, endTime=None):
        """Set a hold at the given temperatures or climate program
        such as 'hoome', 'away', 'sleep'.
        """

        params = {
            'holdType':     holdType,
        }

        if holdClimateRef:
            params['holdClimateRef'] = holdClimateRef
        else:
            if not heatHoldTemp and not coolHoldTemp:
                raise ValueError("one of ('heatHoldTemp', 'coolHoldTemp', 'holdClimateRef') is required")

            # defaults for these are the current temperature
            if not heatHoldTemp:
                heatHoldTemp = self._status[thermostat_id]['runtime']['desiredHeat']
            else:
                heatHoldTemp = int(heatHoldTemp * 10)

            if not coolHoldTemp:
                coolHoldTemp = self._status[thermostat_id]['runtime']['desiredCool']
            else:
                coolHoldTemp = int(coolHoldTemp * 10)

            params['heatHoldTemp'] = heatHoldTemp,
            params['coolHoldTemp'] = coolHoldTemp,


        if holdType == 'holdHours':
            params['holdHours'] = holdHours

        if holdType == 'dateTime':
            params['startDate'] = startDate
            params['endDate']   = endDate
            params['startTime'] = startTime
            params['endTime']   = endTime

        return self.post('thermostat', {
            "selection": {
                "selectionType":  "thermostats",
                "selectionMatch": thermostat_id,
            },
            "functions": [{
                "type": "setHold",
                "params": params,
            }]
        })


    def poll(self):
        """
        Return a list of thermostat IDs that have been updated since the last poll.
        https://www.ecobee.com/home/developer/api/documentation/v1/operations/get-thermostat-summary.shtml

        * NOTE:
            DO NOT poll at an interval quicker than once every 3 minutes,
            which is the shortest interval at which data might change.
        """
        summary = self.thermostatSummary()
        # may not have got a useful response
        if not summary:
            return []

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


    def get_thermostat(self, thermostat_id):
        """return a Thermostat object for the given thermostat"""
        thermostat_id = str(thermostat_id)
        if not self.thermostat_ids:
            self.update()

        if thermostat_id in self.thermostat_ids:
            return Thermostat(self, thermostat_id)

    def list_thermostats(self):
        """Return list of thermostats"""
        if not self.thermostat_ids:
            self.update()

        return list(Thermostat(self, tid) for tid in self.thermostat_ids)


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
        try:
            r = requests.get(url, params = {'json': json.dumps(data)}, headers=self._headers)
            if not r.ok:
                self._handle_error(r)
            else:
                return r.json()

        except requests.exceptions.ConnectionError as e:
            self.log.error(e)
            raise EcobeeException("Connection error: {}".format(e)) from None


    def post(self, endpoint, data):
        """Ecobee API-specific wrapper for requests.post"""
        self.authorize_refresh()

        url = self.url_api.format(endpoint=endpoint)
        try:
            r = requests.post(url, data = json.dumps(data), headers=self._headers)

            if not r.ok:
                self._handle_error(r)
            else:
                return r.json()

        except requests.exceptions.ConnectionError as e:
            self.log.error(e)
            self.log.error(r.request)
            raise EcobeeException("Connection error: {}".format(e)) from None


    def _handle_error(self, response):
        try:
            data = response.json()
            # code 16 = auth needs refresh
            if data['status']['code'] == 14:
                self.log.warning("error 14: auth token needs refresh")
                return self.authorize_refresh(force=True)

            # code 16 = auth revoked, clear the token and start again
            if data['status']['code'] == 16:
                self.log.warning("error 16: restarting authentication")
                self.auth['refresh_token'] = None
                self.auth['token_type'] = None
                return self.authorize_start()

            # otherwise just raise it
            errmsg = '{}: {}'.format(data['status']['code'], data['status']['message'])
            self.log.error(errmsg)
            raise EcobeeException(errmsg)

        # failed to parse the JSON so this must be bad
        except ValueError:
            self.log.error("Response not JSON: {}".format(response.text))
            raise EcobeeException("Response not JSON: {}".format(response.text)) from None


    def _raw_get(self, endpoint, **kwargs):
        """Mostly-raw GET used for authentication API"""
        h = {'Content-Type': 'application/json;charset=UTF-8'}
        url = self.url_base + endpoint
        try:
            return requests.get(url, params=kwargs, headers=h)
        except requests.exceptions.ConnectionError as e:
            self.log.error(e)
            raise EcobeeException("Connection error: {}".format(e)) from None


    def _raw_post(self, endpoint, **kwargs):
        """Mostly-raw POST used for authentication API"""
        h = {'Content-Type': 'application/json;charset=UTF-8'}
        url = self.url_base + endpoint
        try:
            return requests.post(url, params=kwargs, headers=h)
        except requests.exceptions.ConnectionError as e:
            self.log.error(e)
            raise EcobeeException("Connection error: {}".format(e)) from None
