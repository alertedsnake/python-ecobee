

## Ecobee

This is a simple library to talk to an [Ecobee](https://www.ecobee.com)
thermostat.

## Usage

    import ecobee
    import pprint

    eapi = ecobee.Ecobee(APIKEY, THERMOSTAT_ID)
    pprint.pprint(eapi.thermostat(includeSensors=True))
