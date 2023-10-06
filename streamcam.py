#!/usr/bin/python3

import os
import io
import logging
import socketserver
import time
import glob
import json
from http import server
from threading import Condition
from gpiozero import CPUTemperature

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>WebCam</title>
    <style>
    img { max-width: 100%; height: auto; }
    img.list { width: 480px; height: 270px; }
    </style>
</head>
<body>
<h1>WebCam</h1>
<script>
    function snap() {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", "/snap");
        xhr.send();
        xhr.responseType = "json";
        xhr.onload = () => {
          if (xhr.readyState == 4 && xhr.status == 200) {
            console.log(xhr.response.filename);
            var img = document.getElementById("preview");
            img.src = xhr.response.filename;
          } else {
            console.log(`Error: ${xhr.status}`);
          }
        };
    }

    function temp() {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", "/temp");
        xhr.send();
        xhr.responseType = "json";
        xhr.onload = () => {
          if (xhr.readyState == 4 && xhr.status == 200) {
            console.log(xhr.response.temp);
            document.getElementById("temperature").innerHTML = xhr.response.temp;
          } else {
            console.log(`Error: ${xhr.status}`);
          }
        };
    }

    function list() {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", "/list");
        xhr.send();
        xhr.responseType = "json";
        xhr.onload = () => {
          if (xhr.readyState == 4 && xhr.status == 200) {
            console.log(xhr.response.filesnames);
            var piclist = document.getElementById("piclist");
            piclist.replaceChildren();
            xhr.response.filesnames.forEach(function(image) {
              var link = document.createElement('a');
              var img = document.createElement('img');
              link.setAttribute("href", image);
              img.classList.add('list')
              link.appendChild(img)
              img.src = image;
              piclist.appendChild(link);
            });
          } else {
            console.log(`Error: ${xhr.status}`);
          }
        };
    }
</script>
<p style="text-align:center;">
    <button id="temperature" onClick='temp()'>Temp</button>
    <button onClick='snap()'>Snapshot</button>
    <button onClick='list()'>List</button>
    <img src="stream.mjpg" width="960" height="540"  alt="meeeh"/>
    <img id="preview" width="960" height="540" alt="Preview"/>
</p>

<p id="piclist">
</p>

</body>
</html>
"""

__location__ = os.path.realpath(
    os.path.join(os.getcwd(), os.path.dirname(__file__)))

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        if self.path.endswith(".jpg"):
            f = open(__location__ + self.path, 'rb')
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.end_headers()
            self.wfile.write(f.read())
            f.close()
            return
        elif self.path == '/snap':
            filename = snap()
            json_data = {'filename': filename}
            json_to_pass = json.dumps(json_data)
            self.send_response(code=200, message='all good here')
            self.send_header(keyword='Content-type', value='application/json')
            self.end_headers()
            self.wfile.write(json_to_pass.encode('utf-8'))
        elif self.path == '/list':
            pics = list()
            json_data = {'filesnames': pics}
            json_to_pass = json.dumps(json_data)
            self.send_response(code=200, message='all good here')
            self.send_header(keyword='Content-type', value='application/json')
            self.end_headers()
            self.wfile.write(json_to_pass.encode('utf-8'))
        elif self.path == '/temp':
            cpu = CPUTemperature()
            json_data = {'temp': cpu.temperature}
            json_to_pass = json.dumps(json_data)
            self.send_response(code=200, message='all good here')
            self.send_header(keyword='Content-type', value='application/json')
            self.end_headers()
            self.wfile.write(json_to_pass.encode('utf-8'))
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (1920, 1080)}))
output = StreamingOutput()
picam2.start_recording(MJPEGEncoder(), FileOutput(output))

def snap():
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    request = picam2.capture_request()
    request.save("main", timestamp + ".jpg")
    request.release()
    return timestamp + ".jpg"

def list():
    jpgFilenamesList = glob.glob('*.jpg')
    return jpgFilenamesList

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    picam2.stop_recording()