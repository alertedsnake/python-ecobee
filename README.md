

## Ecobee

This is a simple library to talk to an [Ecobee](https://www.ecobee.com)
thermostat.

## Usage

    >>> import ecobee

    >>> eapi = ecobee.Client(APIKEY, [THERMOSTAT_ID])
    >>> eapi.update()

    >>> t = eapi.get_thermostat(THERMOSTAT_ID)
    >>> t.settings.get('hvacMode')
    'heat'

    >>> s = t.get_sensor('ei:0')
    >>> print('{}: {}°F'.format(s.name, s.temperature))
    Main Floor: 70.3°F

## Event loop

You will probably want to use some kind of event loop where you call
eapi.poll() (this method is referenced inside Thermostat and Sensor)
on a regular basis, though the data is only updated every three minutes,
so there's no need to do this often.

When poll() returns a thermostat ID, then you would all update() to refresh
the data about that thermostat.

Implementation is of course up to the reader.


## Reference material

Ecobee has lots of great documentation here:
  https://www.ecobee.com/home/developer/api/documentation/v1/index.shtml


## Python version

This library was designed to work with Python 3.  It seems to work with 2.7.10,
but I haven't done any real testing, and probably don't intend to.

