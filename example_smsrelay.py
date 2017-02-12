from sms_relay import SMSdispatcher, SMSrelay, SMSdispatchtype
from sqlitewrap import SqliteWrap
import sqlite3  # For sqlite3.OperationalError

"""
A simple application using SMSrelay,
It shows examples of three ways to setup patterns to match.
See test() for examples of messages received and responded to.
"""

class TestDispatcher(SMSdispatcher):

    @classmethod
    def thank(cls, msg):
        return { "phonenumber": msg.phonenumber, "message": "Thanks a bunch" }

# An example of a defined function as a dispatch pattern
TestDispatcher.update(strings = ["hello","bonjour"], f=TestDispatcher.thank, type=SMSdispatchtype.STRINGIN )

# An example of a simple lambda function as a dispatch pattern
TestDispatcher.update(strings = ["echo"], f=lambda msg: { "phonenumber": msg.phonenumber, "message": "echo "+msg.message}, type=SMSdispatchtype.STRINGIN)

# An example of a regex function as a dispatch pattern
TestDispatcher.update(regex=[r"name is (?P<name>[A-Za-z ]+?) from (?P<from>[A-Z][a-zA-Z]+)"], type=SMSdispatchtype.REGEX,
                     f=lambda msg, r: {"phonenumber": msg.phonenumber,
                                       "message": "Hi %s how is the weather in %s" % (r.group("name"), r.group("from"))})


def test():
    print "Testing Example SMSRelay application"
    SMSrelay.setup(
        databasefile="smsmessagetest.db",           # Connect to the database in this test file
        createTables=True, dropTablesFirst=True,    # Create tables, removing whatever was there first
        dispatcher = TestDispatcher,                # Class to handle incoming
    )
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'hello', 'from': u'+16177171111',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100001'})
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0',
                                    'gsm_strength': u'[38]', 'charging': u'true', 'device_id': u'1007'})
    assert resp["message"] == "Thanks a bunch", "Should be response from TestDispatcher"

    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'echo ping', 'from': u'+16177171111',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100002'})
    # Should queue a message "Thanks a bunch"
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0',
                                    'gsm_strength': u'[38]', 'charging': u'true', 'device_id': u'1007'})
    assert resp["message"] == "echo echo ping"

    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'Hi my name is Fred from London', 'from': u'+16177171111',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100003'})
    # Should queue a message "Thanks a bunch"
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0',
                                    'gsm_strength': u'[38]', 'charging': u'true', 'device_id': u'1007'})
    assert resp["message"] == "Hi Fred how is the weather in London"


    SMSrelay.done()
