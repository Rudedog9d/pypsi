#
# Copyright (c) 2014, Adam Meily
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice, this
#   list of conditions and the following disclaimer in the documentation and/or
#   other materials provided with the distribution.
#
# * Neither the name of the {organization} nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

from io import StringIO
import json
from pypsi.remote import protocol as proto
import select
import errno


class RemoteKeyboardInterrupt(KeyboardInterrupt):
    pass


class ConnectionClosed(EOFError):
    pass


class RemotePypsiSession(object):

    def __init__(self, socket=None):
        self.socket = socket
        self.queue = []
        self.buffer = StringIO()
        self.registry = {
            proto.InputRequest.status: proto.InputRequest,
            proto.InputResponse.status: proto.InputResponse,
            proto.CompletionRequest.status: proto.CompletionRequest,
            proto.CompletionResponse.status: proto.CompletionResponse,
            proto.InputRequest.status: proto.InputRequest,
            proto.ShellOutputResponse.status: proto.ShellOutputResponse
        }
        self.running = True

    def on_send(self, obj):
        return obj

    def on_recv(self, obj):
        return obj

    def send_json(self, obj):
        #self.p("send:", obj)
        try:
            c = self.socket.sendall(json.dumps(obj).encode())
            if c:
                raise ConnectionClosed

            c = self.socket.sendall(b'\x00')
            if c:
                raise ConnectionClosed
        except OSError as e:
            if e.errno in (errno.EPIPE, 10053):
                raise ConnectionClosed
            raise e

        return 0

    def poll(self):
        fd = self.socket.fileno()
        (read, write, err) = select.select([fd], [], [fd], 0.5)
        if read or err:
            return True
        return False

    def recv_json(self, block=True):
        if self.queue:
            return json.loads(self.queue.pop(0))

        while self.running:
            if self.poll():
                s = None
                try:
                    s = self.socket.recv(0x1000)
                except OSError as e:
                    if e.errno == errno.EPIPE:
                        raise ConnectionClosed
                    raise e
                else:
                    if not s:
                        raise ConnectionClosed

                s = str(s, 'utf-8')
                msg = None
                delims = s.count('\x00')
                if delims > 0:
                    msgs = s.split('\x00')
                    if self.buffer.tell() != 0:
                        self.buffer.write(msgs.pop(0))
                        msg = self.buffer.getvalue()
                        self.buffer = StringIO()
                    else:
                        msg = msgs.pop(0)

                    # msg 0 msg ; delims = 1, c = 1
                    # 0 msg ; delims = 1, c = 1
                    # msg 0 msg 0 ; delims = 2, c = 1
                    msgs = [m for m in msgs if m]
                    if msgs:
                        if len(msgs) >= delims:
                            self.buffer.write(msgs.pop())
                            self.queue = msgs
                        else:
                            self.queue = msgs

                    if msg:
                        return json.loads(msg)
                else:
                    self.buffer.write(s)

            if not block:
                return None

        return None

    def sendmsg(self, msg):
        '''
        try:
            rc = self.send_json(msg.json())
        except ConnectionClosed:
            raise EOFError
        else:
            return rc
        '''
        m = self.on_send(msg.json())
        return self.send_json(m)

    def recvmsg(self, block=True):
        obj = self.recv_json(block)
        obj = self.on_recv(obj)
        if obj: 
            return self.parse_msg(obj)
        return None

    def parse_msg(self, obj):
        if 'status' not in obj:
            raise proto.InvalidMessage("missing required field status")

        s = obj['status']
        if s in self.registry:
            return self.registry[s].from_json(obj)
        raise proto.InvalidMessage("unknown status "+s)
