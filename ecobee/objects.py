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

    @property
    def mode(self):
        """What is the current HVAC mode?"""
        return self.settings.get('hvacMode')

    @property
    def state(self):
        """What is the current hvac state?"""
        if self.is_heating:
            return 'heat'
        if self.is_cooling:
            return 'cool'
        return 'idle'

    @property
    def is_fan(self):
        """Is the fan on ?"""
        if not self.runtime:
            return None
        return 'fan' in self.running

    @property
    def is_heating(self):
        """Is this thing currently heating?"""
        if not self.runtime:
            return None
        for key in ('heatPump', 'heatPump2', 'heatPump3', 'auxHeat1', 'auxHeat2', 'auxHeat3'):
            if key in self.running:
                return True
        return False

    @property
    def is_cooling(self):
        """Is this thing currently cooling?"""
        if not self.runtime:
            return None
        for key in ('compCool1', 'compCool2'):
            if key in self.running:
                return True
        return False


    @property
    def target_temperature(self):
        """Return target humidity, independent of mode"""

        if not self.runtime:
            return None
        if self.mode == 'heat' or (self.mode == 'auto' and self.is_heating):
            return self.runtime.get('desiredHeat') / 10.0
        if self.mode == 'cool' or (self.mode == 'auto' and self.is_cooling):
            return self.runtime.get('desiredCool') / 10.0
        return None

    @property
    def target_humidity(self):
        """Return target humidity"""
        if not self.runtime:
            return None
        return self.runtime.get('desiredHumidity')


    @property
    def current_temperature(self):
        if not self.runtime:
            return None
        return self.runtime.get('actualTemperature') / 10.0

    @property
    def current_humidity(self):
        if not self.runtime:
            return None
        return self.runtime.get('actualHumidity')


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
            try:
                return int(val) / 10.0
            except ValueError:
                return None

    @property
    def humidity(self):
        """Return humidity (float) or None if not supported"""
        val = self._get_capability('humidity').get('value')
        if val:
            try:
                return int(val)
            except ValueError:
                return None

    @property
    def occupancy(self):
        """Return occupancy (boolean) or None if not supported"""
        val = self._get_capability('occupancy').get('value')
        if val:
            return val == 'true'

    @property
    def updated(self):
        return self.thermostat.updated

    def can(self, key):
        """Can this sensor do that?"""
        for obj in self._status.get('capability', []):
            if obj['type'] == key:
                return True
        return False

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

