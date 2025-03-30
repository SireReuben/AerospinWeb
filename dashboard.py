import json
import asyncio
import logging
import os
from aiohttp import web, ClientSession
from datetime import datetime, timedelta  # Correct import
import matplotlib.pyplot as plt
import numpy as np
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from cachetools import TTLCache
from threading import Lock

# Configuration
PORT = int(os.environ.get("PORT", 10000))
MAX_HISTORY = 20
VALID_DEVICE_STATES = ["disconnected", "ready", "waiting", "running", "stopped", "restarting"]
VALID_TRANSITIONS = {
    "disconnected": ["ready"],
    "ready": ["waiting"],
    "waiting": ["running", "ready"],
    "running": ["stopped", "restarting"],
    "stopped": ["ready", "restarting"],
    "restarting": ["ready"]
}
VALID_AUTH_CODE_MIN = 100
VALID_AUTH_CODE_MAX = 999
GOOGLE_API_KEY = "AIzaSyDpCPfntL6CEXPoOVPf2RmfmCjfV7rfano"  # Replace with your key
AUTH_TIMEOUT_MINUTES = 5

# Global state with thread safety
state_lock = Lock()
data_lock = Lock()

# Shared resources
shared_state = {
    "device_state": "disconnected",
    "auth_data": {
        "code": None,
        "runtime": None,
        "expires": None
    },
    "session_data": [],
    "operational_data": {
        "temperature": 0,
        "humidity": 0,
        "speed": 0,
        "remaining": 0,
        "history": {
            "temperature": [],
            "humidity": [],
            "speed": [],
            "remaining": [],
            "timestamps": []
        },
        "gps": {
            "latitude": None,
            "longitude": None,
            "source": None,
            "accuracy": None
        },
        "vpn_info": {
            "is_vpn": False,
            "confidence": 0,
            "details": "No data yet"
        }
    }
}

vpn_cache = TTLCache(maxsize=100, ttl=300)
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
        .vpn-tooltip {
            position: relative;
            display: inline-block;
            cursor: help;
        }
        .vpn-tooltip .tooltip-text {
            visibility: hidden;
            width: 250px;
            background-color: #1f2937;
            color: #f9fafb;
            text-align: center;
            border-radius: 6px;
            padding: 8px;
            position: absolute;
            z-index: 1;
            bottom: 125%;
            left: 50%;
            margin-left: -125px;
            opacity: 0;
            transition: opacity 0.3s;
            border: 1px solid #4cc9f0;
            font-size: 12px;
        }
        .vpn-tooltip:hover .tooltip-text {
            visibility: visible;
            opacity: 1;
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
                        <div id="speed" class="metric-value">0<span class="metric-unit">%</span></div>
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
                <div class="col-md-3">
                    <div class="metric-card vpn-status">
                        <div class="metric-title"><i class="ri-shield-check-line"></i> VPN Status</div>
                        <div id="vpnStatus" class="metric-value vpn-tooltip">
                            Unknown
                            <span class="tooltip-text" id="vpnDetails">No data yet</span>
                        </div>
                    </div>
                </div>
                <div class="col-md-3"><div class="chart-container"><canvas id="tempChart"></canvas></div></div>
                <div class="col-md-3"><div class="chart-container"><canvas id="humidChart"></canvas></div></div>
                <div class="col-md-3"><div class="chart-container"><canvas id="speedChart"></canvas></div></div>
            </div>
            <div class="row">
                <div class="col-md-4">
                    <div class="control-card">
                        <h4 class="mb-3">Control Panel</h4>
                        <div class="mb-3">
                            <label for="authMethod" class="form-label">Authentication Method</label>
                            <select id="authMethod" class="form-control">
                                <option value="code">Code Entry</option>
                                <option value="yesno">Yes/No</option>
                            </select>
                        </div>
                        <div id="codeInput" class="mb-3">
                            <label for="authCode" class="form-label">Auth Code (100-999)</label>
                            <input type="number" id="authCode" min="100" max="999" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label for="runtime" class="form-label">Runtime (seconds)</label>
                            <input type="number" id="runtime" min="1" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label for="speedControl" class="form-label">Initial Speed (%)</label>
                            <input type="range" id="speedControl" min="0" max="100" value="50" class="form-control">
                            <span id="speedValue" class="metric-unit">50%</span>
                        </div>
                        <div id="liveSpeedControl" style="display: none;">
                            <label for="liveSpeed" class="form-label">Live Speed Control (%)</label>
                            <input type="range" id="liveSpeed" min="0" max="100" class="form-control">
                            <span id="liveSpeedValue" class="metric-unit">0%</span>
                        </div>
                        <div id="yesNoAuth" class="mb-3" style="display: none;">
                            <label class="form-label">Start Now?</label>
                            <button id="yesButton" class="btn btn-success me-2">Yes</button>
                            <button id="noButton" class="btn btn-danger">No</button>
                        </div>
                        <button id="submitSetup" class="btn btn-primary w-100">Configure System</button>
                        <button id="stopButton" class="btn btn-danger w-100 mt-2" style="display: none;">
                            <i class="ri-restart-line"></i> Restart System
                        </button>
                        <button id="downloadPdf" class="btn btn-primary w-100 mt-2" style="display: none;">Download Report</button>
                        <button id="startNewSession" class="btn btn-success w-100 mt-2" style="display: none;">
                            <i class="ri-restart-line"></i> New Session
                        </button>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="chart-container" style="height: 300px;">
                        <div id="map"></div>
                    </div>
                </div>
            </div>
            <div class="row">
                <div class="col-md-12"><div class="chart-container"><canvas id="remainingChart"></canvas></div></div>
            </div>
        </div>
    </div>
    <script>
        let tempChart, humidChart, speedChart, remainingChart;
        let map, marker;
        let previousState = "disconnected";
        let isMapInitialized = false;

        function initCharts() {
            const commonOptions = {
                responsive: true,
                maintainAspectRatio: false,
                scales: { 
                    x: { 
                        display: true, 
                        ticks: { 
                            maxRotation: 45, 
                            minRotation: 45,
                            color: '#9ca3af'
                        },
                        grid: { color: 'rgba(156, 163, 175, 0.1)' }
                    }, 
                    y: { 
                        beginAtZero: false,
                        ticks: { color: '#9ca3af' },
                        grid: { color: 'rgba(156, 163, 175, 0.1)' }
                    } 
                },
                plugins: { 
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#1f2937',
                        titleColor: '#f9fafb',
                        bodyColor: '#f9fafb',
                        borderColor: '#4cc9f0',
                        borderWidth: 1
                    }
                }
            };
            
            tempChart = new Chart(document.getElementById('tempChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#f72585', borderWidth: 2, pointBackgroundColor: '#f72585', pointRadius: 3, pointHoverRadius: 5, tension: 0.1, fill: false }] },
                options: commonOptions
            });
            
            humidChart = new Chart(document.getElementById('humidChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#4cc9f0', borderWidth: 2, pointBackgroundColor: '#4cc9f0', pointRadius: 3, pointHoverRadius: 5, tension: 0.1, fill: false }] },
                options: commonOptions
            });
            
            speedChart = new Chart(document.getElementById('speedChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#4361ee', borderWidth: 2, pointBackgroundColor: '#4361ee', pointRadius: 3, pointHoverRadius: 5, tension: 0.1, fill: false }] },
                options: commonOptions
            });
            
            remainingChart = new Chart(document.getElementById('remainingChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#9b59b6', borderWidth: 2, pointBackgroundColor: '#9b59b6', pointRadius: 3, pointHoverRadius: 5, tension: 0.1, fill: false }] },
                options: commonOptions
            });
        }

        function updateCharts(data) {
            console.log("Updating charts with data:", data.history);
            const maxPoints = 20;
            const timestamps = data.history.timestamps.slice(-maxPoints);
            
            tempChart.data.labels = timestamps;
            tempChart.data.datasets[0].data = data.history.temperature.slice(-maxPoints);
            tempChart.update();
            
            humidChart.data.labels = timestamps;
            humidChart.data.datasets[0].data = data.history.humidity.slice(-maxPoints);
            humidChart.update();
            
            discutirChart.data.labels = timestamps;
            speedChart.data.datasets[0].data = data.history.speed.slice(-maxPoints);
            speedChart.update();
            
            remainingChart.data.labels = timestamps;
            remainingChart.data.datasets[0].data = data.history.remaining.slice(-maxPoints);
            remainingChart.update();
        }

        function resetCharts() {
            tempChart.data.labels = [];
            tempChart.data.datasets[0].data = [];
            tempChart.update();
            
            humidChart.data.labels = [];
            humidChart.data.datasets[0].data = [];
            humidChart.update();
            
            speedChart.data.labels = [];
            speedChart.data.datasets[0].data = [];
            speedChart.update();
            
            remainingChart.data.labels = [];
            remainingChart.data.datasets[0].data = [];
            remainingChart.update();
        }

        function initMap() {
            map = new google.maps.Map(document.getElementById('map'), {
                center: { lat: 20, lng: 54 },
                zoom: 2,
                mapTypeId: 'roadmap',
                mapId: '67926741dcbb2036'  // Replace with your Vector Map ID
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
                console.log(`Updating map to Arduino location: Lat ${latitude}, Lon ${longitude}`);
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
            } else {
                console.warn("No valid coordinates provided for map update");
            }
        }

        function updateSystemStatus(status, isActive = false) {
            const statusElement = document.getElementById('systemStatus');
            if (statusElement) {
                statusElement.innerHTML = isActive ? 
                    '<i class="ri-checkbox-circle-line"></i> ' + status : 
                    '<i class="ri-focus-3-line"></i> ' + status;
                statusElement.className = isActive ? 'status-badge active' : 'status-badge';
            }
        }

        function initControlPanel() {
            const authMethod = document.getElementById('authMethod');
            const codeInput = document.getElementById('codeInput');
            const yesNoAuth = document.getElementById('yesNoAuth');
            const speedControl = document.getElementById('speedControl');
            const speedValue = document.getElementById('speedValue');
            const liveSpeed = document.getElementById('liveSpeed');
            const liveSpeedValue = document.getElementById('liveSpeedValue');

            authMethod.addEventListener('change', function() {
                if (this.value === 'code') {
                    codeInput.style.display = 'block';
                    yesNoAuth.style.display = 'none';
                } else {
                    codeInput.style.display = 'none';
                    yesNoAuth.style.display = 'block';
                }
            });

            speedControl.addEventListener('input', function() {
                speedValue.textContent = `${this.value}%`;
            });

            liveSpeed.addEventListener('change', async function() {
                liveSpeedValue.textContent = `${this.value}%`;
                await sendSpeedToArduino(this.value);
            });

            document.getElementById('yesButton').addEventListener('click', async function() {
                await submitYesNo(true);
            });

            document.getElementById('noButton').addEventListener('click', async function() {
                await submitYesNo(false);
            });
        }

        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            waitForGoogleMaps();
            initControlPanel();
            document.getElementById('submitSetup').addEventListener('click', submitSetup);
            document.getElementById('stopButton').addEventListener('click', stopSystem);
            document.getElementById('downloadPdf').addEventListener('click', downloadPdf);
            document.getElementById('startNewSession').addEventListener('click', startNewSession);
            setInterval(fetchData, 1000);
        });

        async function submitSetup() {
            const authMethod = document.getElementById('authMethod').value;
            const runtime = parseInt(document.getElementById('runtime').value);
            const speed = parseInt(document.getElementById('speedControl').value);

            if (isNaN(runtime) || runtime < 1) {
                alert("Runtime must be a positive number.");
                return;
            }

            let payload = { runtime: runtime, speed: speed };
            
            if (authMethod === 'code') {
                const authCode = parseInt(document.getElementById('authCode').value);
                if (isNaN(authCode) || authCode < 100 || authCode > 999) {
                    alert("Auth code must be between 100 and 999.");
                    return;
                }
                payload.authCode = authCode;
            } else {
                payload.authMethod = 'yesno';
            }

            try {
                const response = await fetch('/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const result = await response.json();
                
                if (result.status === 'waiting') {
                    updateSystemStatus('Waiting');
                    document.getElementById('submitSetup').disabled = true;
                    fetchData();
                } else {
                    alert("Setup failed: " + result.error);
                }
            } catch (error) {
                console.error('Error submitting setup:', error);
                alert('Failed to submit setup.');
            }
        }

        async function stopSystem() {
            try {
                const response = await fetch('/stop', {
                    method: 'POST'
                });
                if (response.ok) {
                    const result = await response.json();
                    if (result.status === 'restart') {
                        updateSystemStatus('Restarting');
                        setTimeout(() => {
                            window.location.reload();
                        }, 5000);
                    }
                } else {
                    alert('Failed to restart system.');
                }
            } catch (error) {
                console.error('Error restarting system:', error);
                alert('Failed to restart system.');
            }
        }

        async function downloadPdf() {
            try {
                const response = await fetch('/download_pdf');
                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `aerospin_report_${new Date().toISOString().replace(/[:.]/g, '-')}.pdf`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                } else {
                    alert('No report available.');
                }
            } catch (error) {
                console.error('Error downloading PDF:', error);
                alert('Failed to download report.');
            }
        }

        async function startNewSession() {
            try {
                const response = await fetch('/reset', {
                    method: 'POST'
                });
                if (response.ok) {
                    document.getElementById('submitSetup').disabled = false;
                    fetchData();
                } else {
                    alert('Failed to start new session.');
                }
            } catch (error) {
                consoleError('Error starting new session:', error);
                alert('Failed to start new session.');
            }
        }

        async function sendSpeedToArduino(speed) {
            try {
                const response = await fetch('/speed', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ speed: parseInt(speed) })
                });
                if (response.ok) {
                    console.log(`Speed ${speed} sent to Arduino`);
                }
            } catch (error) {
                console.error('Error sending speed:', error);
            }
        }

        async function submitYesNo(confirm) {
            try {
                const response = await fetch('/yesno', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirm: confirm })
                });
                if (response.ok) {
                    fetchData();
                }
            } catch (error) {
                console.error('Error submitting Yes/No:', error);
            }
        }

        async function fetchData() {
            try {
                const response = await fetch('/data');
                const data = await response.json();
                console.log("Fetched data:", data);
                const currentState = data.state;

                updateSystemStatus(currentState.charAt(0).toUpperCase() + currentState.slice(1), currentState === 'running');
                
                if (data.data_received) {
                    const tempElement = document.getElementById('temperature');
                    const humidElement = document.getElementById('humidity');
                    const speedElement = document.getElementById('speed');
                    const remainElement = document.getElementById('remaining');
                    if (tempElement) tempElement.innerHTML = `${data.temperature.toFixed(1)}<span class="metric-unit">°C</span>`;
                    if (humidElement) humidElement.innerHTML = `${data.humidity.toFixed(1)}<span class="metric-unit">%</span>`;
                    if (speedElement) speedElement.innerHTML = `${data.speed}<span class="metric-unit">%</span>`;
                    if (remainElement) remainElement.innerHTML = `${data.remaining}<span class="metric-unit">s</span>`;
                    
                    const vpnStatus = document.getElementById('vpnStatus');
                    const vpnDetails = document.getElementById('vpnDetails');
                    if (data.vpn_info && vpnStatus && vpnDetails) {
                        vpnStatus.innerHTML = data.vpn_info.is_vpn ? 
                            `<span style="color: #f72585">Active (${data.vpn_info.confidence}%)</span>` : 
                            `<span style="color: #4ade80">Inactive (${data.vpn_info.confidence}%)</span>`;
                        vpnDetails.textContent = data.vpn_info.details;
                    }
                    
                    updateCharts(data);

                    if (data.gps?.latitude != null && data.gps?.longitude != null) {
                        console.log(`Arduino GPS data received: Lat ${data.gps.latitude}, Lon ${data.gps.longitude}`);
                        updateMap(data.gps.latitude, data.gps.longitude);
                    } else if (!fetchData.gpsWarned) {
                        console.warn("No GPS data available; map will not update.");
                        fetchData.gpsWarned = true;
                    }

                    const liveSpeedControl = document.getElementById('liveSpeedControl');
                    const liveSpeed = document.getElementById('liveSpeed');
                    if (currentState === 'running') {
                        liveSpeedControl.style.display = 'block';
                        liveSpeed.value = data.speed;
                        document.getElementById('liveSpeedValue').textContent = `${data.speed}%`;
                    } else {
                        liveSpeedControl.style.display = 'none';
                    }
                }

                if (currentState === 'disconnected') {
                    const tempElement = document.getElementById('temperature');
                    const humidElement = document.getElementById('humidity');
                    const speedElement = document.getElementById('speed');
                    const remainElement = document.getElementById('remaining');
                    if (tempElement) tempElement.innerHTML = `0<span class="metric-unit">°C</span>`;
                    if (humidElement) humidElement.innerHTML = `0<span class="metric-unit">%</span>`;
                    if (speedElement) speedElement.innerHTML = `0<span class="metric-unit">%</span>`;
                    if (remainElement) remainElement.innerHTML = `0<span class="metric-unit">s</span>`;
                    resetCharts();
                    fetchData.gpsWarned = false;
                }

                const stopButton = document.getElementById('stopButton');
                const downloadButton = document.getElementById('downloadPdf');
                const newSessionButton = document.getElementById('startNewSession');
                if (stopButton) stopButton.style.display = 
                    (currentState === 'running' || currentState === 'waiting' || currentState === 'ready') ? 'block' : 'none';
                if (downloadButton) downloadButton.style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';
                if (newSessionButton) newSessionButton.style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';

                previousState = currentState;

            } catch (error) {
                console.error('Error fetching data:', error);
                updateSystemStatus('Connection Error');
            }
        }
        fetchData.gpsWarned = false;

    </script>
</body>
</html>
'''

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("server.log")
    ]
)

async def cors_middleware(app, handler):
    async def middleware(request):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers.update({
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600"
        })
        return response
    return middleware

async def logging_middleware(app, handler):
    async def middleware(request):
        start = datetime.now()  # Fixed datetime usage
        response = await handler(request)
        duration = (datetime.now() - start).total_seconds()  # Fixed datetime usage
        logging.info(f"{request.method} {request.path} - {response.status} - {duration:.2f}s")
        return response
    return middleware

def set_device_state(new_state):
    with state_lock:
        current_state = shared_state["device_state"]
        if new_state in VALID_TRANSITIONS.get(current_state, []):
            logging.info(f"State change: {current_state} -> {new_state}")
            shared_state["device_state"] = new_state
            return True
        logging.error(f"Invalid state transition: {current_state} -> {new_state}")
        return False

def update_operational_data(field, value):
    with data_lock:
        if field in shared_state["operational_data"]:
            shared_state["operational_data"][field] = value
        elif field in shared_state["operational_data"]["history"]:
            shared_state["operational_data"]["history"][field].append(value)
            if len(shared_state["operational_data"]["history"][field]) > MAX_HISTORY:
                shared_state["operational_data"]["history"][field] = \
                    shared_state["operational_data"]["history"][field][-MAX_HISTORY:]

def get_auth_status():
    with state_lock:
        return (
            shared_state["auth_data"]["code"] is not None and 
            shared_state["auth_data"]["expires"] is not None and 
            datetime.now() < shared_state["auth_data"]["expires"]  # Fixed datetime usage
        )

async def check_vpn(ip_address):
    if ip_address in vpn_cache:
        logging.debug(f"VPN status from cache for {ip_address}")
        return vpn_cache[ip_address]
    
    vpn_indicators = []
    confidence_score = 0
    
    try:
        async with ClientSession() as session:
            url = f"https://ip-api.com/json/{ip_address}?fields=status,message,proxy,hosting,org"
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        if data.get("proxy", False):
                            vpn_indicators.append("Proxy detected")
                            confidence_score += 40
                        if data.get("hosting", False):
                            vpn_indicators.append("Hosting provider")
                            confidence_score += 30
                        org = data.get("org", "").lower()
                        if any(keyword in org for keyword in ["vpn", "proxy", "cloud", "hosting"]):
                            vpn_indicators.append(f"Org: {org}")
                            confidence_score += 20

        is_vpn = confidence_score >= 50
        details = "; ".join(vpn_indicators) if vpn_indicators else "No VPN indicators"
        vpn_info = {
            "is_vpn": is_vpn,
            "confidence": min(confidence_score, 100),
            "details": f"{details} (Note: Detection is approximate)"
        }
        
        vpn_cache[ip_address] = vpn_info
        logging.info(f"VPN check for {ip_address}: {vpn_info}")
        return vpn_info
    except Exception as e:
        logging.error(f"VPN check failed for {ip_address}: {e}")
        vpn_info = {"is_vpn": False, "confidence": 0, "details": f"Check failed: {str(e)}"}
        vpn_cache[ip_address] = vpn_info
        return vpn_info

async def get_gps_from_ip(ip_address):
    logging.debug(f"Attempting IP geolocation for: {ip_address}")
    try:
        async with ClientSession() as session:
            url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_API_KEY}"
            payload = {"considerIp": True}
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    accuracy = data.get("accuracy", 0)
                    logging.info(f"Google Geolocation response: {data}")
                    if accuracy < 50000:
                        return {
                            "latitude": data["location"]["lat"],
                            "longitude": data["location"]["lng"],
                            "source": "google_geolocation",
                            "accuracy": accuracy
                        }

            ip_url = f"https://ip-api.com/json/{ip_address}?fields=status,message,lat,lon"
            async with session.get(ip_url) as response:
                if response.status == 200:
                    ip_data = await response.json()
                    logging.info(f"IP-API response: {ip_data}")
                    if ip_data.get("status") == "success":
                        return {
                            "latitude": ip_data["lat"],
                            "longitude": ip_data["lon"],
                            "source": "ip_api",
                            "accuracy": 50000
                        }
    
    except Exception as e:
        logging.error(f"Geolocation error for IP {ip_address}: {e}")
    
    return {"latitude": None, "longitude": None, "source": None, "accuracy": None}

async def handle_data(request):
    try:
        if request.method == "POST":
            post_data = await request.json()
            status = post_data.get("status")
            client_ip = request.headers.get("X-Forwarded-For", request.remote)

            # VPN check
            shared_state["operational_data"]["vpn_info"] = await check_vpn(client_ip)

            if status == "arduino_ready":
                with state_lock:
                    if shared_state["device_state"] != "ready" and set_device_state("ready"):  # Prevent ready -> ready
                        logging.info(f"Arduino ready from {client_ip}")
                return web.json_response({
                    "status": "ready",
                    "state": shared_state["device_state"],
                    "requires_action": "setup"
                })

            elif status == "check_auth":
                response_data = {
                    "status": "waiting",
                    "state": shared_state["device_state"],
                    "timestamp": datetime.now().isoformat()  # Fixed datetime usage
                }
                if get_auth_status():
                    response_data.update({
                        "status": "auth_code",
                        "code": shared_state["auth_data"]["code"],
                        "runtime": shared_state["auth_data"]["runtime"]
                    })
                elif shared_state["device_state"] == "waiting" and shared_state["auth_data"]["code"] is None:
                    response_data.update({
                        "status": "yes_no",
                        "runtime": shared_state["auth_data"]["runtime"]
                    })
                return web.json_response(response_data)

            elif status == "data":
                with data_lock:
                    for field in ["temperature", "humidity", "speed", "remaining"]:
                        if field in post_data:
                            shared_state["operational_data"][field] = post_data[field]
                            update_operational_data(field, post_data[field])
                    
                    timestamp = datetime.now().strftime("%H:%M:%S")  # Fixed datetime usage
                    update_operational_data("timestamps", timestamp)
                    
                    if not shared_state["operational_data"]["gps"]["latitude"]:
                        gps_data = await get_gps_from_ip(client_ip)
                        shared_state["operational_data"]["gps"].update(gps_data)

                return web.json_response({"status": "data_received"})

            elif status == "start":
                if set_device_state("running"):
                    return web.json_response({"status": "start", "state": "running"})
                return web.json_response({"error": "Invalid state for start"}, status=400)

            elif status == "stopped":
                if set_device_state("stopped"):
                    return web.json_response({"status": "stopped", "state": "stopped"})
                return web.json_response({"error": "Invalid state for stop"}, status=400)

            else:
                logging.warning(f"Unknown status: {status}")
                return web.json_response({"error": "invalid_status"}, status=400)

        elif request.method == "GET":
            with data_lock:
                response_data = {
                    "state": shared_state["device_state"],
                    "data_received": bool(shared_state["operational_data"]["history"]["timestamps"]),
                    **shared_state["operational_data"],
                    "auth_valid": get_auth_status(),
                    "auth_expires": shared_state["auth_data"]["expires"].isoformat() if shared_state["auth_data"]["expires"] else None
                }
            return web.json_response(response_data)

    except Exception as e:
        logging.error(f"Data handler error: {str(e)}")
        return web.json_response({"error": "server_error"}, status=500)

async def handle_setup(request):
    try:
        post_data = await request.json()
        runtime = post_data.get("runtime")
        speed = post_data.get("speed", 0)

        if not (isinstance(runtime, int) and runtime > 0):
            return web.json_response({"error": "invalid_runtime"}, status=400)
        
        if not (isinstance(speed, int) and 0 <= speed <= 100):
            return web.json_response({"error": "invalid_speed"}, status=400)

        with state_lock:
            if shared_state["device_state"] != "ready":
                return web.json_response({"error": "Device not ready"}, status=400)

            if "authCode" in post_data:
                auth_code = post_data.get("authCode")
                if not (VALID_AUTH_CODE_MIN <= auth_code <= VALID_AUTH_CODE_MAX):
                    return web.json_response({"error": "invalid_code"}, status=400)
                shared_state["auth_data"]["code"] = auth_code
            else:
                shared_state["auth_data"]["code"] = None

            shared_state["auth_data"]["runtime"] = runtime
            shared_state["auth_data"]["expires"] = datetime.now() + timedelta(minutes=AUTH_TIMEOUT_MINUTES)  # Fixed datetime usage
            shared_state["operational_data"]["speed"] = speed

            if set_device_state("waiting"):
                return web.json_response({"status": "waiting"})
            return web.json_response({"error": "State transition failed"}, status=500)

    except Exception as e:
        logging.error(f"Setup error: {str(e)}")
        return web.json_response({"error": "server_error"}, status=500)

async def handle_debug(request):
    with state_lock, data_lock:
        debug_info = {
            "device_state": shared_state["device_state"],
            "auth_code": shared_state["auth_data"]["code"],
            "auth_expires": shared_state["auth_data"]["expires"].isoformat() if shared_state["auth_data"]["expires"] else None,
            "runtime": shared_state["auth_data"]["runtime"],
            "session_data_count": len(shared_state["session_data"]),
            "last_gps": shared_state["operational_data"]["gps"],
            "current_values": {k: v for k, v in shared_state["operational_data"].items() if k != "history"}
        }
    return web.json_response(debug_info)

async def handle_yesno(request):
    try:
        post_data = await request.json()
        confirm = post_data.get("confirm", False)
        
        with state_lock:
            if shared_state["device_state"] == "waiting" and confirm:
                if set_device_state("running"):
                    return web.json_response({"status": "start", "state": "running"})
            return web.json_response({"status": "waiting", "state": shared_state["device_state"]})
    except Exception as e:
        logging.error(f"Error in Yes/No handling: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_stop(request):
    try:
        with state_lock:
            if set_device_state("restarting"):
                logging.info("Sending restart command")
                return web.json_response({"status": "restart", "state": "restarting"})
            return web.json_response({"error": "Invalid state transition"}, status=400)
    except Exception as e:
        logging.error(f"Stop error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_speed(request):
    try:
        if request.method == "POST":
            post_data = await request.json()
            speed = post_data.get("speed")
            if not isinstance(speed, int) or speed < 0 or speed > 100:
                return web.json_response({"error": "Invalid speed"}, status=400)
            
            with data_lock:
                if shared_state["device_state"] == "running":
                    shared_state["operational_data"]["speed"] = speed
                    update_operational_data("speed", speed)
                    logging.info(f"Speed updated to {speed}")
                    return web.json_response({"status": "speed_set", "speed": speed})
                return web.json_response({"error": "Device not running"}, status=400)
        with data_lock:
            return web.json_response({"speed": shared_state["operational_data"]["speed"]})
    except Exception as e:
        logging.error(f"Error handling speed: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_reset(request):
    try:
        with state_lock, data_lock:
            shared_state["device_state"] = "ready"
            shared_state["session_data"] = []
            shared_state["auth_data"]["code"] = None
            shared_state["auth_data"]["runtime"] = None
            shared_state["auth_data"]["expires"] = None
            shared_state["operational_data"]["temperature"] = 0
            shared_state["operational_data"]["humidity"] = 0
            shared_state["operational_data"]["speed"] = 0
            shared_state["operational_data"]["remaining"] = 0
            shared_state["operational_data"]["history"] = {
                "temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []
            }
            shared_state["operational_data"]["gps"] = {
                "latitude": None, "longitude": None, "source": None, "accuracy": None
            }
            shared_state["operational_data"]["vpn_info"] = {
                "is_vpn": False, "confidence": 0, "details": "No data yet"
            }
            logging.info("Session reset initiated")
        return web.json_response({"status": "reset", "state": "ready"})
    except Exception as e:
        logging.error(f"Error resetting session: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_download_pdf(request):
    try:
        with data_lock:
            if not shared_state["operational_data"]["history"]["timestamps"]:
                return web.json_response({"error": "No session data available"}, status=400)
        
        filename = generate_pdf(shared_state["operational_data"]["history"])
        with open(filename, 'rb') as f:
            pdf_content = f.read()
        
        response = web.Response(
            body=pdf_content,
            content_type='application/pdf',
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Access-Control-Allow-Origin": "*"
            }
        )
        os.remove(filename)
        return response
    except Exception as e:
        logging.error(f"Error generating PDF: {e}")
        return web.json_response({"error": str(e)}, status=500)

def generate_pdf(history_data):
    filename = f"aerospin_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"  # Fixed datetime usage
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Aerospin Session Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))  # Fixed datetime usage
    if shared_state["operational_data"]["gps"]["latitude"]:
        elements.append(Paragraph(
            f"Device Location: Lat {shared_state['operational_data']['gps']['latitude']:.6f}, "
            f"Lon {shared_state['operational_data']['gps']['longitude']:.6f} "
            f"(Source: {shared_state['operational_data']['gps']['source']}, "
            f"Accuracy: {shared_state['operational_data']['gps']['accuracy']}m)",
            styles['Normal']
        ))
    elements.append(Spacer(1, 12))

    if not history_data["timestamps"]:
        elements.append(Paragraph("No data collected during this session", styles['Normal']))
        doc.build(elements)
        return filename

    timestamps = history_data["timestamps"]
    temperatures = history_data["temperature"]
    humidities = history_data["humidity"]
    speeds = history_data["speed"]
    remainings = history_data["remaining"]

    summary_data = [
        ["Metric", "Minimum", "Maximum", "Average"],
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
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(Paragraph("Summary Statistics", styles['Heading2']))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    plt.figure(figsize=(10, 8))
    plt.subplot(4, 1, 1)
    plt.plot(timestamps, temperatures, label='Temperature', color='red')
    plt.title('Temperature Variation')
    plt.ylabel('Temperature (°C)')
    plt.xticks(rotation=45)
    plt.legend()

    plt.subplot(4, 1, 2)
    plt.plot(timestamps, humidities, label='Humidity', color='blue')
    plt.title('Humidity Variation')
    plt.ylabel('Humidity (%)')
    plt.xticks(rotation=45)
    plt.legend()

    plt.subplot(4, 1, 3)
    plt.plot(timestamps, speeds, label='Speed', color='green')
    plt.title('Speed Variation')
    plt.ylabel('Speed (%)')
    plt.xticks(rotation=45)
    plt.legend()

    plt.subplot(4, 1, 4)
    plt.plot(timestamps, remainings, label='Time Remaining', color='purple')
    plt.title('Time Remaining Variation')
    plt.ylabel('Time (s)')
    plt.xlabel('Timestamp')
    plt.xticks(rotation=45)
    plt.legend()

    plt.tight_layout()
    canvas = FigureCanvas(plt.gcf())
    img_buffer = io.BytesIO()
    canvas.print_png(img_buffer)
    img_buffer.seek(0)
    plt_img = Image(img_buffer)
    plt_img.drawWidth = 500
    plt_img.drawHeight = 400
    elements.append(Paragraph("Graphical Analysis", styles['Heading2']))
    elements.append(plt_img)
    plt.close()

    table_data = [["Timestamp", "Temperature (°C)", "Humidity (%)", "Speed (%)", "Time Remaining (s)", "Latitude", "Longitude"]]
    for i in range(len(timestamps)):
        table_data.append([
            timestamps[i],
            f"{temperatures[i]:.1f}",
            f"{humidities[i]:.1f}",
            f"{speeds[i]}",
            f"{remainings[i]}",
            f"{shared_state['operational_data']['gps']['latitude']:.6f}" if shared_state['operational_data']['gps']['latitude'] else "N/A",
            f"{shared_state['operational_data']['gps']['longitude']:.6f}" if shared_state['operational_data']['gps']['longitude'] else "N/A"
        ])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))
    
    elements.append(Paragraph("Detailed Session Data", styles['Heading2']))
    elements.append(table)

    doc.build(elements)
    logging.info(f"PDF generated: {filename}")
    return filename

async def handle_root(request):
    return web.Response(
        text=HTML_CONTENT,
        content_type='text/html',
        charset='utf-8'
    )

async def init_app():
    app = web.Application(middlewares=[cors_middleware, logging_middleware])
    app.router.add_get('/', handle_root)
    app.router.add_route('*', '/data', handle_data)
    app.router.add_post('/setup', handle_setup)
    app.router.add_get('/debug', handle_debug)
    app.router.add_post('/yesno', handle_yesno)
    app.router.add_post('/stop', handle_stop)
    app.router.add_route('*', '/speed', handle_speed)
    app.router.add_post('/reset', handle_reset)
    app.router.add_get('/download_pdf', handle_download_pdf)
    return app

if __name__ == "__main__":
    logging.info(f"Starting server on port {PORT}")
    web.run_app(init_app(), host="0.0.0.0", port=PORT)

