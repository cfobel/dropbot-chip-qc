import threading

from dropbot_monitor.mqtt_proxy import MqttProxy
import dropbot as db


class DropBotMqttProxy(MqttProxy):
    def __init__(self, *args, **kwargs):
        super(DropBotMqttProxy, self).__init__(*args, **kwargs)
        super(DropBotMqttProxy, self).__setattr__('transaction_lock',
                                                  threading.RLock())

    @classmethod
    def from_uri(cls, *args, **kwargs):
        return super(DropBotMqttProxy, cls).from_uri(db.proxy.Proxy, *args,
                                                     **kwargs)
