import json
import asyncio
import logging
import os
from aiohttp import web, ClientSession
import datetime
import matplotlib.pyplot as plt
import numpy as np
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from cachetools import TTLCache

PORT = int(os.environ.get("PORT", 10000))
MAX_HISTORY = 20
VALID_DEVICE_STATES = ["disconnected", "ready", "waiting", "running", "stopped"]
VALID_AUTH_CODE_MIN = 100
VALID_AUTH_CODE_MAX = 999
GOOGLE_API_KEY = "AIzaSyDpCPfntL6CEXPoOVPf2RmfmCjfV7rfano"  # Replace with your actual Google API key

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("server.log")]
)

data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
data_received = False
device_state = "disconnected"
session_data = []
auth_code = None
runtime = None
gps_coords = {"latitude": None, "longitude": None, "source": None, "accuracy": None}
vpn_cache = TTLCache(maxsize=100, ttl=300)
vpn_info = {"is_vpn": False, "confidence": 0, "details": "No data yet"}
pending_auth = False

HTML_CONTENT = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aerospin Control Center</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/remixicon@3.5.0/fonts/remixicon.css" rel="stylesheet">
    <script async defer src="https://maps.googleapis.com/maps/api/js?key=''' + GOOGLE_API_KEY + '''&libraries=places,marker&v=weekly"></script>
    <style>
        :root {
            --primary: #4361ee;
            --secondary: #3a0ca3;
            --accent: #4cc9f0;
            --warning: #f72585;
            --success: #4ade80;
            --background: #111827;
            --card-bg: #1f2937;
            --text: #f9fafb;
            --text-secondary: #9ca3af;
            --border: #374151;
        }
        body {
            background: var(--background);
            color: var(--text);
            font-family: 'Roboto', sans-serif;
            margin: 0;
            padding: 30px;
            line-height: 1.6;
        }
        .container { 
            max-width: 1300px; 
            padding: 20px; 
        }
        .dashboard {
            border-radius: 16px;
            padding: 24px;
            background: linear-gradient(135deg, 
                rgba(31, 41, 55, 0.95), 
                rgba(17, 24, 39, 0.98));
            border: 1px solid rgba(55, 65, 81, 0.5);
            box-shadow: 
                0 15px 35px rgba(0, 0, 0, 0.3), 
                0 5px 15px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        .header h1 {
            font-size: 24px;
            font-weight: 600;
            margin: 0;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .header h1 i { 
            color: var(--accent); 
            transition: transform 0.3s ease;
        }
        .header h1 i:hover {
            transform: rotate(15deg) scale(1.1);
        }
        .status-badge {
            background: rgba(67, 97, 238, 0.15);
            color: var(--accent);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s ease;
        }
        .status-badge:hover {
            transform: scale(1.05);
            background: rgba(67, 97, 238, 0.25);
        }
        .status-badge.active {
            background: rgba(74, 222, 128, 0.15);
            color: var(--success);
        }
        .metric-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid var(--border);
            transition: 
                transform 0.4s cubic-bezier(0.25, 0.1, 0.25, 1),
                box-shadow 0.4s cubic-bezier(0.25, 0.1, 0.25, 1);
            position: relative;
            overflow: hidden;
        }
        .metric-card::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(
                45deg, 
                transparent, 
                rgba(255,255,255,0.05), 
                transparent
            );
            transform: rotate(-45deg);
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        .metric-card:hover::before {
            opacity: 1;
        }
        .metric-card:hover {
            transform: translateY(-8px) scale(1.02);
            box-shadow: 
                0 15px 30px rgba(0, 0, 0, 0.3), 
                0 0 20px rgba(67, 97, 238, 0.2);
        }
        .metric-title {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 500;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .metric-value {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 4px;
            letter-spacing: -1px;
        }
        .metric-unit {
            font-size: 16px;
            color: var(--text-secondary);
            margin-left: 5px;
        }
        .chart-container {
            position: relative;
            height: 220px;
            margin-bottom: 24px;
            background: rgba(31, 41, 55, 0.6);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid var(--border);
            backdrop-filter: blur(10px);
            transition: 
                transform 0.4s cubic-bezier(0.25, 0.1, 0.25, 1),
                box-shadow 0.4s cubic-bezier(0.25, 0.1, 0.25, 1);
        }
        .chart-container:hover {
            transform: translateY(-8px) scale(1.02);
            box-shadow: 
                0 15px 30px rgba(0, 0, 0, 0.3), 
                0 0 20px rgba(67, 97, 238, 0.2);
        }
        .control-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
            border: 1px solid var(--border);
            transition: all 0.3s ease;
        }
        .control-card:hover {
            transform: translateY(-5px);
            box-shadow: 
                0 10px 20px rgba(0, 0, 0, 0.2);
        }
        .btn-primary { 
            background-color: var(--primary); 
            border-color: var(--primary); 
            border-radius: 25px;
            padding: 10px 20px;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
            transition: 
                background-color 0.3s ease,
                transform 0.3s ease,
                box-shadow 0.3s ease;
        }
        .btn-primary:hover {
            background-color: var(--secondary);
            border-color: var(--secondary);
            transform: translateY(-3px);
            box-shadow: 0 7px 14px rgba(0, 0, 0, 0.25);
        }
        .btn-danger { 
            background-color: var(--warning); 
            border-color: var(--warning); 
            border-radius: 25px;
            padding: 10px 20px;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
            transition: 
                background-color 0.3s ease,
                transform 0.3s ease,
                box-shadow 0.3s ease;
        }
        .btn-danger:hover {
            background-color: #d3165e;
            border-color: #d3165e;
            transform: translateY(-3px);
            box-shadow: 0 7px 14px rgba(0, 0, 0, 0.25);
        }
        .btn-success { 
            background-color: var(--success); 
            border-color: var(--success); 
            border-radius: 25px;
            padding: 10px 20px;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
            transition: 
                background-color 0.3s ease,
                transform 0.3s ease,
                box-shadow 0.3s ease;
        }
        .btn-success:hover {
            background-color: #38b260;
            border-color: #38b260;
            transform: translateY(-3px);
            box-shadow: 0 7px 14px rgba(0, 0, 0, 0.25);
        }
        .form-control {
            background-color: var(--background);
            color: var(--text);
            border-color: var(--border);
            transition: all 0.3s ease;
        }
        .form-control:focus {
            background-color: var(--background);
            color: var(--text);
            border-color: var(--primary);
            outline: none;
            box-shadow: 
                0 0 0 3px rgba(67, 97, 238, 0.3),
                0 0 0 1px rgba(67, 97, 238, 0.8);
        }
        #map { 
            height: 100%; 
            width: 100%; 
            border-radius: 12px;
            border: 1px solid var(--border);
        }
        .speed-control {
            position: relative;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .speed-control:hover {
            transform: scale(1.05);
            color: var(--accent);
        }
        .speed-control.active {
            color: var(--accent);
            font-weight: bold;
        }
        .speed-control.disabled {
            opacity: 0.7;
            pointer-events: none;
        }
        .status-tooltip {
            position: absolute;
            background: var(--card-bg);
            border: 1px solid var(--border);
            padding: 8px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 100;
            display: none;
        }
        #speed:hover + .status-tooltip {
            display: block;
        }
        @media (max-width: 768px) {
            .metric-card, .chart-container {
                margin-bottom: 15px;
            }
        }
    </style>
</head>
<body>
    <div class="container" id="dashboard">
        <div class="dashboard">
            <div class="header">
                <h1><i class="ri-dashboard-3-line"></i> Aerospin Control Center</h1>
                <div id="systemStatus" class="status-badge"><i class="ri-focus-3-line"></i> Disconnected</div>
            </div>
            <div class="row">
                <div class="col-md-3">
                    <div class="metric-card temperature">
                        <div class="metric-title"><i class="ri-temp-hot-line"></i> Temperature</div>
                        <div id="temperature" class="metric-value">0<span class="metric-unit">°C</span></div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="metric-card humidity">
                        <div class="metric-title"><i class="ri-drop-line"></i> Humidity</div>
                        <div id="humidity" class="metric-value">0<span class="metric-unit">%</span></div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="metric-card speed">
                        <div class="metric-title"><i class="ri-speed-line"></i> Speed</div>
                        <div id="speed" class="metric-value speed-control">0<span class="metric-unit">%</span></div>
                        <div class="status-tooltip">Click to adjust speed (only available when running)</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="metric-card remaining">
                        <div class="metric-title"><i class="ri-time-line"></i> Time Remaining</div>
                        <div id="remaining" class="metric-value">0<span class="metric-unit">s</span></div>
                    </div>
                </div>
            </div>
            <div class="row">
                <div class="col-md-4">
                    <div class="control-card">
                        <h4 class="mb-3">Control Panel</h4>
                        <button id="setupButton" class="btn btn-primary w-100">Setup System</button>
                        <button id="stopButton" class="btn btn-danger w-100 mt-2" style="display: none;">
                            <i class="ri-stop-circle-line"></i> Stop System
                        </button>
                        <button id="downloadPdf" class="btn btn-primary w-100 mt-2" style="display: none;">Download Report</button>
                        <button id="startNewSession" class="btn btn-success w-100 mt-2" style="display: none;">
                            <i class="ri-restart-line"></i> New Session
                        </button>
                        <div id="speedControls" style="display: none; margin-top: 15px;">
                            <h4 class="mb-3">Speed Control</h4>
                            <div class="d-flex align-items-center mb-3">
                                <button id="decreaseSpeedInline" class="btn btn-primary me-2">-5%</button>
                                <div class="flex-grow-1 text-center">
                                    <div id="speedDisplay" class="metric-value">0%</div>
                                </div>
                                <button id="increaseSpeedInline" class="btn btn-primary ms-2">+5%</button>
                            </div>
                            <input type="range" class="form-range" min="0" max="100" value="0" id="speedSliderInline">
                        </div>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="chart-container" style="height: 300px;">
                        <div id="map"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Speed Control Modal -->
    <div class="modal fade" id="speedModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content" style="background: var(--card-bg); border: 1px solid var(--border);">
                <div class="modal-header" style="border-bottom: 1px solid var(--border);">
                    <h5 class="modal-title">Adjust Speed</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close" style="filter: invert(1);"></button>
                </div>
                <div class="modal-body">
                    <div class="mb-3">
                        <label for="speedSlider" class="form-label">Current Speed: <span id="speedValue">0</span>%</label>
                        <input type="range" class="form-range" min="0" max="100" step="1" id="speedSlider">
                    </div>
                    <div class="d-flex justify-content-between">
                        <button id="decreaseSpeed" class="btn btn-primary"><i class="ri-subtract-line"></i> 5%</button>
                        <button id="increaseSpeed" class="btn btn-primary"><i class="ri-add-line"></i> 5%</button>
                    </div>
                </div>
                <div class="modal-footer" style="border-top: 1px solid var(--border);">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    <button type="button" class="btn btn-primary" id="saveSpeed">Save Changes</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Authentication Modal -->
    <div class="modal fade" id="authModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content" style="background: var(--card-bg); border: 1px solid var(--border);">
                <div class="modal-header" style="border-bottom: 1px solid var(--border);">
                    <h5 class="modal-title">Authentication Method</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close" style="filter: invert(1);"></button>
                </div>
                <div class="modal-body">
                    <div class="mb-3">
                        <div class="form-check">
                            <input class="form-check-input" type="radio" name="authMethod" id="codeAuth" checked>
                            <label class="form-check-label" for="codeAuth">Code Authentication</label>
                        </div>
                        <div class="form-check">
                            <input class="form-check-input" type="radio" name="authMethod" id="buttonAuth">
                            <label class="form-check-label" for="buttonAuth">Button Authentication</label>
                        </div>
                    </div>
                    <div id="codeAuthFields">
                        <div class="mb-3">
                            <label for="authCode" class="form-label">Auth Code (100-999)</label>
                            <input type="number" id="authCode" min="100" max="999" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label for="runtime" class="form-label">Runtime (seconds)</label>
                            <input type="number" id="runtime" min="1" class="form-control" required>
                        </div>
                    </div>
                    <div id="buttonAuthFields" style="display: none;">
                        <div class="alert alert-info">
                            <i class="ri-information-line"></i> This will send a request to the device for approval
                        </div>
                        <div class="mb-3">
                            <label for="buttonRuntime" class="form-label">Runtime (seconds)</label>
                            <input type="number" id="buttonRuntime" min="1" class="form-control" required>
                        </div>
                    </div>
                </div>
                <div class="modal-footer" style="border-top: 1px solid var(--border);">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" id="submitAuth">Authenticate</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let map, marker;
        let isMapInitialized = false;

        function initMap() {
            map = new google.maps.Map(document.getElementById('map'), {
                center: { lat: 20, lng: 54 },
                zoom: 2,
                mapTypeId: 'roadmap',
                mapId: '67926741dcbb2036'
            });
            isMapInitialized = true;
            console.log("Map initialized successfully");
        }

        function waitForGoogleMaps() {
            if (window.google && window.google.maps) {
                initMap();
            } else {
                console.log("Waiting for Google Maps API to load...");
                setTimeout(waitForGoogleMaps, 500);
            }
        }

        function updateMap(latitude, longitude) {
            if (!isMapInitialized || !map) {
                console.error("Map not initialized yet. Retrying...");
                setTimeout(() => updateMap(latitude, longitude), 1000);
                return;
            }
            if (latitude && longitude) {
                const position = { lat: parseFloat(latitude), lng: parseFloat(longitude) };
                if (!marker) {
                    marker = new google.maps.marker.AdvancedMarkerElement({
                        position: position,
                        map: map,
                        title: "Arduino Device Location",
                        content: new google.maps.marker.PinElement({
                            background: '#f59e0b',
                            borderColor: '#136aec',
                            glyphColor: 'transparent',
                            scale: 1.5
                        }).element
                    });
                } else {
                    marker.position = position;
                }
                map.setCenter(position);
                map.setZoom(13);
            }
        }

        function updateSystemStatus(status, isActive = false) {
            const statusElement = document.getElementById('systemStatus');
            const speedElement = document.getElementById('speed');
            const speedControls = document.getElementById('speedControls');
            
            if (statusElement) {
                statusElement.innerHTML = isActive ? 
                    '<i class="ri-checkbox-circle-line"></i> ' + status : 
                    '<i class="ri-focus-3-line"></i> ' + status;
                statusElement.className = isActive ? 'status-badge active' : 'status-badge';
            }
            
            if (speedElement) {
                if (isActive) {
                    speedElement.classList.add('speed-control', 'active');
                    speedElement.classList.remove('disabled');
                    speedElement.style.cursor = 'pointer';
                    speedElement.title = 'Click to adjust speed';
                    speedControls.style.display = 'block';
                } else {
                    speedElement.classList.remove('speed-control', 'active');
                    speedElement.classList.add('disabled');
                    speedElement.style.cursor = 'default';
                    speedElement.title = '';
                    speedControls.style.display = 'none';
                }
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            waitForGoogleMaps();
            
            const speedModal = new bootstrap.Modal(document.getElementById('speedModal'));
            const speedSlider = document.getElementById('speedSlider');
            const speedValue = document.getElementById('speedValue');
            const saveSpeedBtn = document.getElementById('saveSpeed');
            const increaseBtn = document.getElementById('increaseSpeed');
            const decreaseBtn = document.getElementById('decreaseSpeed');
            const speedSliderInline = document.getElementById('speedSliderInline');
            const increaseBtnInline = document.getElementById('increaseSpeedInline');
            const decreaseBtnInline = document.getElementById('decreaseSpeedInline');
            
            document.getElementById('speed').addEventListener('click', function() {
                if (this.classList.contains('active')) {
                    speedSlider.value = parseInt(this.textContent);
                    speedValue.textContent = speedSlider.value;
                    speedModal.show();
                }
            });
            
            speedSlider.addEventListener('input', function() {
                speedValue.textContent = this.value;
            });
            
            increaseBtn.addEventListener('click', function() {
                speedSlider.value = Math.min(100, parseInt(speedSlider.value) + 5);
                speedValue.textContent = speedSlider.value;
            });
            
            decreaseBtn.addEventListener('click', function() {
                speedSlider.value = Math.max(0, parseInt(speedSlider.value) - 5);
                speedValue.textContent = speedSlider.value;
            });
            
            saveSpeedBtn.addEventListener('click', async function() {
                const newSpeed = parseInt(speedSlider.value);
                try {
                    const response = await fetch('/speed', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ speed: newSpeed })
                    });
                    if (response.ok) {
                        speedModal.hide();
                        fetchData();
                    } else {
                        alert('Failed to update speed');
                    }
                } catch (error) {
                    console.error('Error updating speed:', error);
                }
            });
            
            speedSliderInline.addEventListener('change', async function() {
                const newSpeed = parseInt(this.value);
                try {
                    const response = await fetch('/speed', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ speed: newSpeed })
                    });
                    if (response.ok) {
                        fetchData();
                    }
                } catch (error) {
                    console.error('Error updating speed:', error);
                }
            });
            
            increaseBtnInline.addEventListener('click', async function() {
                const currentSpeed = parseInt(speedSliderInline.value);
                const newSpeed = Math.min(100, currentSpeed + 5);
                speedSliderInline.value = newSpeed;
                try {
                    const response = await fetch('/speed', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ speed: newSpeed })
                    });
                    if (response.ok) {
                        fetchData();
                    }
                } catch (error) {
                    console.error('Error updating speed:', error);
                }
            });
            
            decreaseBtnInline.addEventListener('click', async function() {
                const currentSpeed = parseInt(speedSliderInline.value);
                const newSpeed = Math.max(0, currentSpeed - 5);
                speedSliderInline.value = newSpeed;
                try {
                    const response = await fetch('/speed', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ speed: newSpeed })
                    });
                    if (response.ok) {
                        fetchData();
                    }
                } catch (error) {
                    console.error('Error updating speed:', error);
                }
            });
            
            const authModal = new bootstrap.Modal(document.getElementById('authModal'));
            const codeAuth = document.getElementById('codeAuth');
            const buttonAuth = document.getElementById('buttonAuth');
            const codeAuthFields = document.getElementById('codeAuthFields');
            const buttonAuthFields = document.getElementById('buttonAuthFields');
            
            document.getElementById('setupButton').addEventListener('click', function() {
                authModal.show();
            });
            
            codeAuth.addEventListener('change', function() {
                if (this.checked) {
                    codeAuthFields.style.display = 'block';
                    buttonAuthFields.style.display = 'none';
                }
            });
            
            buttonAuth.addEventListener('change', function() {
                if (this.checked) {
                    codeAuthFields.style.display = 'none';
                    buttonAuthFields.style.display = 'block';
                }
            });
            
            document.getElementById('submitAuth').addEventListener('click', async function() {
                const useButtonAuth = buttonAuth.checked;
                if (useButtonAuth) {
                    const runtime = document.getElementById('buttonRuntime').value;
                    if (!runtime || runtime < 1) {
                        alert('Please enter a valid runtime');
                        return;
                    }
                    try {
                        const response = await fetch('/auth/request', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ 
                                type: 'button',
                                runtime: parseInt(runtime)
                            })
                        });
                        if (response.ok) {
                            authModal.hide();
                            updateSystemStatus('Waiting');
                        } else {
                            alert('Failed to send authentication request');
                        }
                    } catch (error) {
                        console.error('Error with button auth:', error);
                    }
                } else {
                    const authCode = document.getElementById('authCode').value;
                    const runtime = document.getElementById('runtime').value;
                    if (!authCode || authCode < 100 || authCode > 999 || !runtime || runtime < 1) {
                        alert('Invalid auth code or runtime');
                        return;
                    }
                    try {
                        const response = await fetch('/setup', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ 
                                type: 'code',
                                authCode: parseInt(authCode),
                                runtime: parseInt(runtime)
                            })
                        });
                        if (response.ok) {
                            authModal.hide();
                            updateSystemStatus('Waiting');
                        } else {
                            alert('Setup failed');
                        }
                    } catch (error) {
                        console.error('Error with code auth:', error);
                    }
                }
            });
            
            document.getElementById('stopButton').addEventListener('click', async function() {
                try {
                    const response = await fetch('/stop', { method: 'POST' });
                    if (response.ok) {
                        fetchData();
                    }
                } catch (error) {
                    console.error('Error stopping system:', error);
                }
            });
            
            setInterval(fetchData, 1000);
        });

        async function fetchData() {
            try {
                const response = await fetch('/data');
                const data = await response.json();
                const currentState = data.state;
                
                updateSystemStatus(currentState.charAt(0).toUpperCase() + currentState.slice(1), 
                                 currentState === 'running');
                
                if (data.data_received) {
                    document.getElementById('temperature').innerHTML = `${data.temperature.toFixed(1)}<span class="metric-unit">°C</span>`;
                    document.getElementById('humidity').innerHTML = `${data.humidity.toFixed(1)}<span class="metric-unit">%</span>`;
                    document.getElementById('speed').innerHTML = `${data.speed}<span class="metric-unit">%</span>`;
                    document.getElementById('remaining').innerHTML = `${data.remaining}<span class="metric-unit">s</span>`;
                    document.getElementById('speedDisplay').textContent = `${data.speed}%`;
                    document.getElementById('speedSliderInline').value = data.speed;
                    if (data.gps.latitude && data.gps.longitude) {
                        updateMap(data.gps.latitude, data.gps.longitude);
                    }
                }
                
                document.getElementById('stopButton').style.display = 
                    (currentState === 'running' || currentState === 'waiting') ? 'block' : 'none';
                document.getElementById('downloadPdf').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';
                document.getElementById('startNewSession').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';
            } catch (error) {
                console.error('Error fetching data:', error);
            }
        }
    </script>
</body>
</html>
'''

async def check_vpn(ip_address):
    if ip_address in vpn_cache:
        return vpn_cache[ip_address]
    
    vpn_info = {"is_vpn": False, "confidence": 0, "details": "Basic check"}
    vpn_cache[ip_address] = vpn_info
    return vpn_info

async def get_gps_from_ip(ip_address):
    try:
        async with ClientSession() as session:
            url = f"http://ip-api.com/json/{ip_address}?fields=status,message,lat,lon"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        return {
                            "latitude": data["lat"],
                            "longitude": data["lon"],
                            "source": "ip_api",
                            "accuracy": 50000
                        }
    except Exception as e:
        logging.error(f"Geolocation error: {e}")
    return {"latitude": None, "longitude": None, "source": None, "accuracy": None}

def generate_pdf(session_data):
    filename = f"aerospin_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Aerospin Session Report", styles['Title']))
    elements.append(Spacer(1, 12))

    if not session_data:
        elements.append(Paragraph("No data collected", styles['Normal']))
        doc.build(elements)
        return filename

    timestamps = [entry["timestamp"] for entry in session_data]
    temperatures = [entry["temperature"] for entry in session_data]
    humidities = [entry["humidity"] for entry in session_data]
    speeds = [entry["speed"] for entry in session_data]
    remainings = [entry["remaining"] for entry in session_data]

    summary_data = [
        ["Metric", "Min", "Max", "Avg"],
        ["Temperature (°C)", f"{min(temperatures):.1f}", f"{max(temperatures):.1f}", f"{np.mean(temperatures):.1f}"],
        ["Humidity (%)", f"{min(humidities):.1f}", f"{max(humidities):.1f}", f"{np.mean(humidities):.1f}"],
        ["Speed (%)", f"{min(speeds)}", f"{max(speeds)}", f"{np.mean(speeds):.1f}"],
        ["Time Remaining (s)", f"{min(remainings)}", f"{max(remainings)}", f"{np.mean(remainings):.1f}"]
    ]
    
    summary_table = Table(summary_data)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(Paragraph("Summary Statistics", styles['Heading2']))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    doc.build(elements)
    return filename

async def handle_data(request):
    global data, history, device_state, data_received, session_data, gps_coords, vpn_info
    
    if request.method == "OPTIONS":
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    if request.method == "POST":
        try:
            post_data = await request.json()
            status = post_data.get("status")
            client_ip = post_data.get("public_ip", request.remote)
            vpn_info = await check_vpn(client_ip)
            gps_coords = await get_gps_from_ip(client_ip)

            if status == "arduino_ready":
                device_state = "ready"
                return web.json_response({"status": "ready", "state": device_state}, headers={"Access-Control-Allow-Origin": "*"})
            
            elif status == "check_auth":
                if auth_code is not None and runtime is not None:
                    return web.json_response({"status": "auth_code", "code": auth_code, "runtime": runtime, "state": device_state}, headers={"Access-Control-Allow-Origin": "*"})
                return web.json_response({"status": "waiting", "state": device_state}, headers={"Access-Control-Allow-Origin": "*"})
            
            elif status == "start":
                device_state = "running"
                return web.json_response({"status": "running", "state": device_state}, headers={"Access-Control-Allow-Origin": "*"})
            
            elif status == "stopped":
                device_state = "stopped"
                return web.json_response({"status": "stopped", "state": device_state}, headers={"Access-Control-Allow-Origin": "*"})
            
            elif status == "data":
                data.update({
                    "temperature": post_data.get("temperature", data["temperature"]),
                    "humidity": post_data.get("humidity", data["humidity"]),
                    "speed": post_data.get("speed", data["speed"]),
                    "remaining": post_data.get("remaining", data["remaining"])
                })
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                session_data.append({**data, "timestamp": timestamp, **gps_coords})
                for key in data:
                    history[key].append(data[key])
                    history[key] = history[key][-MAX_HISTORY:]
                history["timestamps"].append(timestamp)
                history["timestamps"] = history["timestamps"][-MAX_HISTORY:]
                data_received = True
                device_state = "running"
                return web.json_response({"status": "success", "state": device_state, "gps": gps_coords, "vpn_info": vpn_info}, headers={"Access-Control-Allow-Origin": "*"})
                
        except Exception as e:
            logging.error(f"Error processing data: {e}")
            return web.json_response({"error": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})
    
    return web.json_response({
        "state": device_state,
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "speed": data["speed"],
        "remaining": data["remaining"],
        "data_received": data_received,
        "history": history,
        "gps": gps_coords,
        "vpn_info": vpn_info,
        "show_speed_controls": device_state == "running"
    }, headers={"Access-Control-Allow-Origin": "*"})

async def handle_setup(request):
    global auth_code, runtime, device_state
    try:
        post_data = await request.json()
        auth_code = post_data.get("authCode")
        runtime = post_data.get("runtime")
        if not (VALID_AUTH_CODE_MIN <= auth_code <= VALID_AUTH_CODE_MAX and runtime > 0):
            return web.json_response({"error": "Invalid auth code or runtime"}, status=400)
        device_state = "waiting"
        return web.json_response({"status": "waiting", "state": device_state})
    except Exception as e:
        logging.error(f"Error in setup: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_stop(request):
    global device_state, data_received
    device_state = "stopped"
    data_received = False
    return web.json_response({"status": "stopped", "state": device_state})

async def handle_reset(request):
    global device_state, session_data, auth_code, runtime, data, history, data_received
    device_state = "disconnected"
    session_data = []
    auth_code = None
    runtime = None
    data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
    history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
    data_received = False
    return web.json_response({"status": "disconnected", "state": device_state})

async def handle_pdf_download(request):
    try:
        if not session_data:
            return web.json_response({"error": "No session data"}, status=404)
        pdf_filename = generate_pdf(session_data)
        return web.FileResponse(pdf_filename)
    except Exception as e:
        logging.error(f"Error serving PDF: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_speed(request):
    global data, history
    try:
        post_data = await request.json()
        new_speed = post_data.get("speed")
        if new_speed is not None and 0 <= new_speed <= 100:
            data["speed"] = new_speed
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            history["speed"].append(new_speed)
            history["speed"] = history["speed"][-MAX_HISTORY:]
            history["timestamps"].append(timestamp)
            history["timestamps"] = history["timestamps"][-MAX_HISTORY:]
            return web.json_response({"status": "success", "speed": new_speed}, headers={"Access-Control-Allow-Origin": "*"})
        return web.json_response({"error": "Invalid speed"}, status=400, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        logging.error(f"Error updating speed: {e}")
        return web.json_response({"error": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

async def handle_auth_request(request):
    global device_state, pending_auth, runtime
    try:
        post_data = await request.json()
        if post_data.get("type") == "button":
            runtime = post_data.get("runtime")
            if not runtime or runtime < 1:
                return web.json_response({"error": "Invalid runtime"}, status=400)
            device_state = "waiting"
            pending_auth = True
            return web.json_response({
                "status": "auth_pending",
                "message": "Please confirm on device",
                "state": device_state,
                "runtime": runtime,
                "show_speed_controls": False
            })
        return web.json_response({"error": "Invalid auth type"}, status=400)
    except Exception as e:
        logging.error(f"Error in auth request: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_auth_response(request):
    global device_state, pending_auth, runtime
    try:
        post_data = await request.json()
        if post_data.get("response") == "confirmed":
            runtime = post_data.get("runtime")
            device_state = "running"
            pending_auth = False
            return web.json_response({"status": "auth_success", "state": device_state, "runtime": runtime})
        elif post_data.get("response") == "rejected":
            device_state = "ready"
            pending_auth = False
            return web.json_response({"status": "auth_rejected", "state": device_state})
        return web.json_response({"error": "Invalid response"}, status=400)
    except Exception as e:
        logging.error(f"Error in auth response: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_root(request):
    return web.Response(text=HTML_CONTENT, content_type='text/html')

async def init_app():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_route('*', '/data', handle_data)
    app.router.add_post('/setup', handle_setup)
    app.router.add_post('/stop', handle_stop)
    app.router.add_post('/reset', handle_reset)
    app.router.add_get('/download_pdf', handle_pdf_download)
    app.router.add_post('/speed', handle_speed)
    app.router.add_post('/auth/request', handle_auth_request)
    app.router.add_post('/auth/response', handle_auth_response)
    return app

async def main():
    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Server started at http://0.0.0.0:{PORT}")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())

