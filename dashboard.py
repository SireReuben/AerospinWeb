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

PORT = int(os.environ.get("PORT", 10000))
MAX_HISTORY = 20
VALID_DEVICE_STATES = ["disconnected", "ready", "waiting", "running", "stopped"]
VALID_AUTH_CODE_MIN = 100
VALID_AUTH_CODE_MAX = 999
GOOGLE_API_KEY = "AIzaSyDpCPfntL6CEXPoOVPf2RmfmCjfV7rfano"  # Replace with your Google API key

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
    <script src="https://maps.googleapis.com/maps/api/js?key=''' + GOOGLE_API_KEY + '''&libraries=places"></script>
    <style>
        body { font-family: 'Roboto', sans-serif; background-color: #f3f4f6; padding: 20px; }
        .dashboard { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .header h1 { font-size: 24px; font-weight: 500; color: #1f2937; }
        .status-badge { padding: 5px 10px; border-radius: 15px; font-size: 14px; background: #e5e7eb; color: #6b7280; }
        .status-badge.active { background: #10b981; color: #fff; }
        .metric-card { background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .metric-title { font-size: 16px; color: #6b7280; margin-bottom: 10px; }
        .metric-value { font-size: 28px; font-weight: 500; color: #1f2937; }
        .metric-unit { font-size: 16px; color: #9ca3af; }
        .chart-container { background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); height: 250px; }
        #map { height: 100%; width: 100%; border-radius: 8px; }
        .control-card { background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
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
                <div class="col-md-3"><div class="chart-container"><canvas id="tempChart"></canvas></div></div>
                <div class="col-md-3"><div class="chart-container"><canvas id="humidChart"></canvas></div></div>
                <div class="col-md-3"><div class="chart-container"><canvas id="speedChart"></canvas></div></div>
                <div class="col-md-3"><div class="chart-container"><canvas id="remainingChart"></canvas></div></div>
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
        </div>
    </div>
    <script>
        let tempChart, humidChart, speedChart, remainingChart;
        let map, marker;
        let previousState = "disconnected";

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
                styles: [
                    {
                        "featureType": "all",
                        "elementType": "all",
                        "stylers": [
                            { "saturation": -20 },
                            { "lightness": 10 }
                        ]
                    }
                ]
            });
        }

        function updateMap(latitude, longitude) {
            if (latitude && longitude) {
                console.log(`Updating map to Arduino location: Lat ${latitude}, Lon ${longitude}`);
                const position = { lat: latitude, lng: longitude };
                
                if (!marker) {
                    marker = new google.maps.Marker({
                        position: position,
                        map: map,
                        icon: {
                            path: google.maps.SymbolPath.CIRCLE,
                            scale: 10,
                            fillColor: '#f59e0b',
                            fillOpacity: 0.8,
                            strokeWeight: 2,
                            strokeColor: '#136aec'
                        },
                        title: "Arduino Device Location"
                    });
                } else {
                    marker.setPosition(position);
                }

                map.setCenter(position);
                map.setZoom(13);
            }
        }

        function updateSystemStatus(status, isActive = false) {
            const statusElement = document.getElementById('systemStatus');
            statusElement.innerHTML = isActive ? 
                '<i class="ri-checkbox-circle-line"></i> ' + status : 
                '<i class="ri-focus-3-line"></i> ' + status;
            statusElement.className = isActive ? 'status-badge active' : 'status-badge';
        }

        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            initMap();
            document.getElementById('submitSetup').addEventListener('click', submitSetup);
            document.getElementById('stopButton').addEventListener('click', stopSystem);
            document.getElementById('downloadPdf').addEventListener('click', downloadPdf);
            document.getElementById('startNewSession').addEventListener('click', startNewSession);
            setInterval(fetchData, 1000); // Poll server for Arduino data
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
                    document.getElementById('temperature').innerHTML = `${data.temperature.toFixed(1)}<span class="metric-unit">°C</span>`;
                    document.getElementById('humidity').innerHTML = `${data.humidity.toFixed(1)}<span class="metric-unit">%</span>`;
                    document.getElementById('speed').innerHTML = `${data.speed}<span class="metric-unit">%</span>`;
                    document.getElementById('remaining').innerHTML = `${data.remaining}<span class="metric-unit">s</span>`;
                    updateCharts(data);

                    if (data.gps?.latitude && data.gps?.longitude) {
                        console.log(`Arduino GPS data received: Lat ${data.gps.latitude}, Lon ${data.gps.longitude}`);
                        updateMap(data.gps.latitude, data.gps.longitude);
                    }
                }

                if (currentState === 'disconnected') {
                    document.getElementById('temperature').innerHTML = `0<span class="metric-unit">°C</span>`;
                    document.getElementById('humidity').innerHTML = `0<span class="metric-unit">%</span>`;
                    document.getElementById('speed').innerHTML = `0<span class="metric-unit">%</span>`;
                    document.getElementById('remaining').innerHTML = `0<span class="metric-unit">s</span>`;
                    resetCharts();
                }

                document.getElementById('stopButton').style.display = 
                    (currentState === 'running' || currentState === 'waiting' || currentState === 'ready') ? 'block' : 'none';
                document.getElementById('downloadPdf').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';
                document.getElementById('startNewSession').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';

                previousState = currentState;

            } catch (error) {
                console.error('Error fetching data:', error);
                updateSystemStatus('Connection Error');
            }
        }
    </script>
</body>
</html>
'''

async def get_gps_from_ip(ip_address):
    """IP-based geolocation for the Arduino device"""
    logging.debug(f"Attempting IP geolocation for: {ip_address}")
    try:
        # Try Google Geolocation API first
        url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_API_KEY}"
        payload = {"considerIp": True}
        
        async with ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    accuracy = data.get("accuracy", 0)
                    if accuracy < 50000:  # Only accept if accuracy < 50km
                        logging.info(f"Google Geolocation success: {data}")
                        return {
                            "latitude": data["location"]["lat"],
                            "longitude": data["location"]["lng"],
                            "source": "google_geolocation",
                            "accuracy": accuracy
                        }
        
        # Fallback to IP-API.com
        ip_url = f"http://ip-api.com/json/{ip_address}?fields=status,message,lat,lon"
        async with ClientSession() as session:
            async with session.get(ip_url) as response:
                if response.status == 200:
                    ip_data = await response.json()
                    if ip_data.get("status") == "success":
                        logging.info(f"IP-API success: {ip_data}")
                        return {
                            "latitude": ip_data["lat"],
                            "longitude": ip_data["lon"],
                            "source": "ip_api",
                            "accuracy": 50000  # IP-based is less accurate
                        }
    
    except Exception as e:
        logging.error(f"Geolocation error: {e}")
    
    logging.warning(f"No valid geolocation data for IP: {ip_address}")
    return {"latitude": None, "longitude": None, "source": None, "accuracy": None}

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
    global data, history, device_state, data_received, session_data, gps_coords
    
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
            client_ip = post_data.get("public_ip", request.remote)  # Prefer public_ip from Arduino
            logging.debug(f"Received POST data from IP {client_ip}: {post_data}")

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
                if client_ip and client_ip != "Unknown":
                    coords = await get_gps_from_ip(client_ip)
                    if coords["latitude"] is not None:
                        gps_coords = coords
                        logging.info(f"Updated Arduino location from IP {client_ip}: {gps_coords}")

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
                    
                    logging.info(f"Stored session data from {client_ip}: {session_record}")
                    return web.json_response(
                        {
                            "status": "success", 
                            "state": device_state,
                            "gps": gps_coords
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
        "gps": gps_coords
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
    global device_state, session_data, auth_code, runtime, data, history, data_received, gps_coords
    
    try:
        device_state = "disconnected"
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        gps_coords = {"latitude": None, "longitude": None, "source": None, "accuracy": None}
        logging.info(f"System stopped, state and metrics reset - State: {device_state}")
        return web.json_response({"status": "stopped", "state": device_state})
        
    except Exception as e:
        logging.error(f"Error stopping system: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_reset(request):
    global device_state, session_data, auth_code, runtime, data, history, data_received, gps_coords
    
    try:
        device_state = "disconnected"
        session_data = []
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        gps_coords = {"latitude": None, "longitude": None, "source": None, "accuracy": None}
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
