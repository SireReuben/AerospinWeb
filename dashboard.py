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
GOOGLE_API_KEY = "AIzaSyDpCPfntL6CEXPoOVPf2RmfmCjfV7rfano"  # Replace with your real Google API key

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("server.log")
    ]
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

async def check_vpn(ip_address):
    if ip_address in vpn_cache:
        logging.debug(f"VPN status from cache for {ip_address}")
        return vpn_cache[ip_address]
    
    vpn_indicators = []
    confidence_score = 0
    
    try:
        async with ClientSession() as session:
            url = f"http://ip-api.com/json/{ip_address}?fields=status,message,proxy,hosting,org"
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
            # Google Geolocation API
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
                    else:
                        logging.debug(f"Google accuracy too low: {accuracy}")

            # Fallback to ip-api.com
            ip_url = f"http://ip-api.com/json/{ip_address}?fields=status,message,lat,lon"
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
                    else:
                        logging.warning(f"IP-API failed: {ip_data.get('message', 'Unknown error')}")
                else:
                    logging.warning(f"IP-API request failed with status: {response.status}")
    
    except Exception as e:
        logging.error(f"Geolocation error for IP {ip_address}: {e}")
    
    logging.warning(f"No valid geolocation data for IP: {ip_address}")
    return {"latitude": None, "longitude": None, "source": None, "accuracy": None}

# HTML content remains unchanged; omitted for brevity but should be identical to your original
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
                            <label for="authCode" class="form-label">Auth Code (100-999)</label>
                            <input type="number" id="authCode" min="100" max="999" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label for="runtime" class="form-label">Runtime (seconds)</label>
                            <input type="number" id="runtime" min="1" class="form-control" required>
                        </div>
                        <button id="submitSetup" class="btn btn-primary w-100">Configure System</button>
                        <button id="stopButton" class="btn btn-danger w-100 mt-2" style="display: none;">
                            <i class="ri-stop-circle-line"></i> Stop System
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
            
            speedChart.data.labels = timestamps;
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
                mapId: '67926741dcbb2036'  // Replace with your Vector Map ID from Google Cloud Console
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

        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            waitForGoogleMaps();
            document.getElementById('submitSetup').addEventListener('click', submitSetup);
            document.getElementById('stopButton').addEventListener('click', stopSystem);
            document.getElementById('downloadPdf').addEventListener('click', downloadPdf);
            document.getElementById('startNewSession').addEventListener('click', startNewSession);
            setInterval(fetchData, 1000);
        });

        async function submitSetup() {
            const authCode = parseInt(document.getElementById('authCode').value);
            const runtime = parseInt(document.getElementById('runtime').value);
            
            if (isNaN(authCode) || authCode < 100 || authCode > 999) {
                alert("Auth code must be between 100 and 999.");
                return;
            }
            
            if (isNaN(runtime) || runtime < 1) {
                alert("Runtime must be a positive number.");
                return;
            }
            
            try {
                const response = await fetch('/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ authCode: authCode, runtime: runtime })
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
                    window.location.reload();
                }
            } catch (error) {
                console.error('Error stopping system:', error);
                alert('Failed to stop system.');
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
                console.error('Error starting new session:', error);
                alert('Failed to start new session.');
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

def generate_pdf(session_data):
    filename = f"aerospin_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Aerospin Session Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    if gps_coords["latitude"] and gps_coords["longitude"]:
        elements.append(Paragraph(
            f"Device Location: Lat {gps_coords['latitude']:.6f}, Lon {gps_coords['longitude']:.6f} "
            f"(Source: {gps_coords['source']}, Accuracy: {gps_coords['accuracy']}m)",
            styles['Normal']
        ))
    elements.append(Spacer(1, 12))

    if not session_data:
        elements.append(Paragraph("No data collected during this session", styles['Normal']))
        doc.build(elements)
        return filename

    timestamps = [entry["timestamp"] for entry in session_data]
    temperatures = [entry["temperature"] for entry in session_data]
    humidities = [entry["humidity"] for entry in session_data]
    speeds = [entry["speed"] for entry in session_data]
    remainings = [entry["remaining"] for entry in session_data]

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
    for entry in session_data:
        table_data.append([
            entry["timestamp"],
            f"{entry['temperature']:.1f}",
            f"{entry['humidity']:.1f}",
            f"{entry['speed']}",
            f"{entry['remaining']}",
            f"{entry.get('latitude', 'N/A'):.6f}" if entry.get('latitude') else "N/A",
            f"{entry.get('longitude', 'N/A'):.6f}" if entry.get('longitude') else "N/A"
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
            # Use the public IP provided by Arduino if available
            public_ip = post_data.get("public_ip")
            if public_ip and public_ip != "Unknown":
                client_ip = public_ip
            else:
                client_ip = request.remote
            
            logging.debug(f"Received POST data from IP {client_ip}: {post_data}")

            vpn_info = await check_vpn(client_ip)

            if status == "arduino_ready":
                if device_state == "disconnected":
                    device_state = "ready"
                    logging.info(f"Arduino detected at {client_ip}, state transitioned to: {device_state}")
                return web.json_response(
                    {"status": "ready", "state": device_state},
                    headers={"Access-Control-Allow-Origin": "*"}
                )
            
            elif status == "check_auth":
                if auth_code is not None and runtime is not None:
                    logging.info(f"Sending auth_code: {auth_code}, runtime: {runtime} to {client_ip}")
                    return web.json_response({
                        "status": "auth_code",
                        "code": auth_code,
                        "runtime": runtime,
                        "state": device_state
                    },
                    headers={"Access-Control-Allow-Origin": "*"})
                logging.debug(f"No auth code yet for {client_ip}, state: {device_state}")
                return web.json_response(
                    {"status": "waiting", "state": device_state},
                    headers={"Access-Control-Allow-Origin": "*"}
                )
            
            elif status == "start":
                device_state = "running"
                logging.info(f"State transitioned to: {device_state} for {client_ip}")
                return web.json_response(
                    {"status": "running", "state": device_state},
                    headers={"Access-Control-Allow-Origin": "*"}
                )
            
            elif status == "stopped":
                device_state = "stopped"
                logging.info(f"State transitioned to: {device_state} for {client_ip}")
                return web.json_response(
                    {"status": "stopped", "state": device_state},
                    headers={"Access-Control-Allow-Origin": "*"}
                )
            
            elif status == "data":
                # Get coordinates using the client's public IP
                coords = await get_gps_from_ip(client_ip)
                gps_coords = coords
                logging.info(f"Updated GPS coords for {client_ip}: {gps_coords}")

                required_fields = ['temperature', 'humidity', 'speed', 'remaining']
                if all(field in post_data for field in required_fields):
                    if not (isinstance(post_data["temperature"], (int, float)) and 
                            isinstance(post_data["humidity"], (int, float)) and 
                            isinstance(post_data["speed"], int) and 
                            isinstance(post_data["remaining"], int)):
                        logging.warning(f"Invalid data types in POST data from {client_ip}")
                        return web.json_response(
                            {"error": "Invalid data types"}, 
                            status=400,
                            headers={"Access-Control-Allow-Origin": "*"}
                        )

                    data_received = True
                    device_state = "running"
                    logging.info(f"Arduino data received from {client_ip}, state transitioned to: {device_state}")
                    
                    data.update({field: post_data[field] for field in required_fields})
                    
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    session_record = {
                        "timestamp": timestamp,
                        **{k: post_data[k] for k in required_fields},
                        **gps_coords
                    }
                    session_data.append(session_record)
                    
                    for key in data:
                        history[key].append(data[key])
                        history[key] = history[key][-MAX_HISTORY:]
                    history["timestamps"].append(timestamp)
                    history["timestamps"] = history["timestamps"][-MAX_HISTORY:]
                    
                    logging.debug(f"Updated history: {history}")
                    
                    return web.json_response(
                        {
                            "status": "success", 
                            "state": device_state,
                            "gps": gps_coords,
                            "vpn_info": vpn_info
                        },
                        headers={"Access-Control-Allow-Origin": "*"}
                    )
                
                logging.warning(f"Missing fields in POST data from {client_ip}")
                return web.json_response(
                    {"error": "Missing required fields"}, 
                    status=400,
                    headers={"Access-Control-Allow-Origin": "*"}
                )
                
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON received from {request.remote}")
            return web.json_response(
                {"error": "Invalid JSON"}, 
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )
        except Exception as e:
            logging.error(f"Error processing data from {request.remote}: {e}")
            return web.json_response(
                {"error": "Internal server error"}, 
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )
    
    logging.debug(f"GET request received from {request.remote}, current state: {device_state}")
    return web.json_response({
        "state": device_state,
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "speed": data["speed"],
        "remaining": data["remaining"],
        "data_received": data_received,
        "history": history,
        "gps": gps_coords,
        "vpn_info": vpn_info
    },
    headers={"Access-Control-Allow-Origin": "*"})

async def handle_setup(request):
    global auth_code, runtime, device_state
    
    try:
        post_data = await request.json()
        logging.debug(f"Received setup data: {post_data}")
        
        auth_code = post_data.get("authCode")
        runtime = post_data.get("runtime")
        
        if not (isinstance(auth_code, int) and VALID_AUTH_CODE_MIN <= auth_code <= VALID_AUTH_CODE_MAX) or not (isinstance(runtime, int) and runtime > 0):
            logging.warning(f"Invalid setup data - authCode: {auth_code}, runtime: {runtime}")
            return web.json_response({"error": f"Auth code must be between {VALID_AUTH_CODE_MIN} and {VALID_AUTH_CODE_MAX}"}, status=400)
            
        device_state = "waiting"
        logging.info(f"Setup complete - Auth Code: {auth_code}, Runtime: {runtime}, State: {device_state}")
        return web.json_response({"status": "waiting", "state": device_state})
        
    except json.JSONDecodeError:
        logging.error("Invalid JSON in setup request")
        return web.json_response({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logging.error(f"Error in setup: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_stop(request):
    global device_state, session_data, auth_code, runtime, data, history, data_received, gps_coords, vpn_info
    
    try:
        device_state = "disconnected"
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        gps_coords = {"latitude": None, "longitude": None, "source": None, "accuracy": None}
        vpn_info = {"is_vpn": False, "confidence": 0, "details": "No data yet"}
        logging.info(f"System stopped, state and metrics reset - State: {device_state}")
        return web.json_response({"status": "stopped", "state": device_state})
        
    except Exception as e:
        logging.error(f"Error stopping system: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_reset(request):
    global device_state, session_data, auth_code, runtime, data, history, data_received, gps_coords, vpn_info
    
    try:
        device_state = "disconnected"
        session_data = []
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        gps_coords = {"latitude": None, "longitude": None, "source": None, "accuracy": None}
        vpn_info = {"is_vpn": False, "confidence": 0, "details": "No data yet"}
        logging.info(f"System reset for new session - State: {device_state}")
        return web.json_response({"status": "disconnected", "state": device_state})
        
    except Exception as e:
        logging.error(f"Error resetting system: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_pdf_download(request):
    global session_data
    
    try:
        if not session_data:
            logging.warning("No session data available for PDF download")
            return web.json_response({"error": "No session data available"}, status=404)
            
        pdf_filename = generate_pdf(session_data)
        response = web.FileResponse(pdf_filename)
        return response
        
    except Exception as e:
        logging.error(f"Error serving PDF: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_root(request):
    logging.debug("Root endpoint accessed")
    return web.Response(text=HTML_CONTENT, content_type='text/html')

async def init_app():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_route('*', '/data', handle_data)
    app.router.add_post('/setup', handle_setup)
    app.router.add_post('/stop', handle_stop)
    app.router.add_post('/reset', handle_reset)
    app.router.add_get('/download_pdf', handle_pdf_download)
    return app

async def main():
    try:
        app = await init_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logging.info(f"Server started at http://0.0.0.0:{PORT}")
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
