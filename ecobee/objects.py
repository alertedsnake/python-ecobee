# vim: set fileencoding=utf-8
"""
A simple library to talk to an Ecobee (https://www.ecobee.com) thermostat.
"""

__author__ = 'Michael Stella <ecobee@thismetalsky.org>'


class Thermostat(object):
    """Ecobee thermostat.

    This class is a thin wrapper around the data in
    eapi._status[thermostat_id].

    """

    def __init__(self, eapi, thermostat_id):
        self._eapi = eapi
        self.id = thermostat_id
        self.lastSeen = None

    @property
    def _status(self):
        return self._eapi._status[self.id]

    @property
    def name(self):
        """Thermostat name"""
        return self._status.get('name', 'pending')

    @property
    def settings(self):
        """Settings dict"""
        return self._status.get('settings', {})

    @property
    def runtime(self):
        """Runtime status dict"""
        return self._status.get('runtime', {})

    @property
    def running(self):
        """List of running equiptment"""
        return self._status.get('equipmentStatus', [])

    @property
    def sensors(self):
        """Sensors dict"""
        return self._status.get('remoteSensors', {})

    @property
    def updated(self):
        """When was this last updated"""
        # not updated yet
        if not self.lastSeen:
            if self.id in self._eapi.lastSeen:
                self.lastSeen = self._eapi.lastSeen[self.id]
                return True

        # updated
        elif self.lastSeen < self._eapi.lastSeen[self.id]:
            self.lastSeen = self._eapi.lastSeen[self.id]
            return True

        return False


    def get_sensor(self, id):
        """Return a sensor object given the ID"""
        if id in self.sensors:
            return Sensor(self, id)

    def list_sensors(self):
        """Return a list of sensor objects"""
        return list(Sensor(self, k) for k in self.sensors.keys())


    def poll(self):
        """Polls for an update.  Returns true if there's data available"""
        return self._eapi.poll()


    def update(self):
        """Calls update() on this thermostat"""
        if self.id in self.poll():
            return self._eapi.update(self.id)


    def _get_report(self, **kwargs):
        """Wrapper for eapi.thermostatReport"""

        try:
            data = self._eapi.thermostatReport(self.id, **kwargs)
            return data.get(self.id, {})
        except EcobeeException:
            pass


    def setHold(self, **kwargs):
        """Set a hold"""
        self._eapi.setHold(self.id, **kwargs)

    def setClimate(self, holdClimateRef, **kwargs):
        """Shortcut to setClimate"""
        self._eapi.setHold(self.id, holdClimateRef=holdClimateRef, **kwargs)

    def setHome(self, **kwargs):
        """Shortcut to set 'home' climate"""
        self.setClimate('home', **kwargs)

    def setAway(self, **kwargs):
        """Shortcut to set 'away' climate"""
        self.setClimate('away', **kwargs)

    def resumeProgram(self):
        """Shortcut to resume program"""
        self._eapi.resumeProgram(self.id)


class Sensor(object):
    """An Ecobee remote sensor

    This class is a thin wrapper around the data in
    eapi._status[thermostat.id]['remoteSensors'][sensor_id].

    """

    def __init__(self, thermostat, sensor_id):
        self.thermostat = thermostat
        self.id = sensor_id

    @property
    def _eapi(self):
        return self.thermostat._eapi

    @property
    def _status(self):
        return self.thermostat.sensors.get(self.id, {})

    @property
    def name(self):
        """Sensor name"""
        return self._status.get('name', 'pending')

    @property
    def type(self):
        """Sensor type"""
        return self._status.get('type')

    @property
    def temperature(self):
        """Return temperature (float) or None if not supported"""
        val = self._get_capability('temperature').get('value')
        if val:
            return int(val) / 10.0

    @property
    def humidity(self):
        """Return humidity (float) or None if not supported"""
        val = self._get_capability('humidity').get('value')
        if val:
            return int(val) / 10.0

    @property
    def occupancy(self):
        """Return occupancy (boolean) or None if not supported"""
        val = self._get_capability('occupancy').get('value')
        if val:
            return val == 'true'

    @property
    def updated(self):
        return self.thermostat.updated

    def _get_capability(self, key):
        """Get a capability from the array"""
        for obj in self._status.get('capability', []):
            if obj['type'] == key:
                return obj
        return {}

    def poll(self):
        """Calls the parent's poll()"""
        return self.thermostat.poll()

    def update(self):
        """Calls the parent's update()"""
        self.thermostat.update()

