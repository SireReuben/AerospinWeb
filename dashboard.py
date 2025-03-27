import json
import asyncio
import logging
import os
from aiohttp import web
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

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
data_received = False
device_state = "disconnected"
session_data = []
latest_pdf = None
auth_code = None
runtime = None

def generate_pdf(session_data):
    """Generate a PDF report from the session data."""
    filename = f"aerospin_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Aerospin Session Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
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

    table_data = [["Timestamp", "Temperature (°C)", "Humidity (%)", "Speed (%)", "Time Remaining (s)"]]
    for entry in session_data:
        table_data.append([
            entry["timestamp"],
            f"{entry['temperature']:.1f}",
            f"{entry['humidity']:.1f}",
            f"{entry['speed']}",
            f"{entry['remaining']}"
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
    <style>
        :root {
    --primary: #2c5282;
    --secondary: #1a365d;
    --accent: #63b3ed;
    --warning: #e53e3e;
    --success: #38a169;
    --background: #f0f4f8;
    --card-bg: #ffffff;
    --text: #2d3748;
    --text-secondary: #718096;
    --border: #e2e8f0;
    --shadow: rgba(0, 0, 0, 0.1);
}

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    background: var(--background);
    color: var(--text);
    font-family: 'Inter', 'Roboto', sans-serif;
    margin: 0;
    padding: 30px;
    line-height: 1.6;
}

.container {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 15px;
}

.dashboard {
    background: var(--card-bg);
    border-radius: 16px;
    padding: 32px;
    box-shadow: 
        0 10px 25px var(--shadow),
        0 5px 10px rgba(0, 0, 0, 0.05);
    border: 1px solid var(--border);
    max-width: 1200px;
    margin: 0 auto;
}

.row {
    display: flex;
    flex-wrap: wrap;
    margin: 0 -15px;
}

.col-md-3 {
    flex: 0 0 25%;
    max-width: 25%;
    padding: 0 15px;
}

.col-md-4 {
    flex: 0 0 33.333333%;
    max-width: 33.333333%;
    padding: 0 15px;
}

.col-md-12 {
    flex: 0 0 100%;
    max-width: 100%;
    padding: 0 15px;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 32px;
    padding-bottom: 24px;
    border-bottom: 2px solid var(--border);
}

.header h1 {
    font-size: 32px;
    font-weight: 800;
    margin: 0;
    color: var(--primary);
    display: flex;
    align-items: center;
    gap: 12px;
}

.header h1 i {
    color: var(--accent);
    margin-right: 10px;
}

.status-badge {
    background: var(--accent);
    color: white;
    padding: 8px 18px;
    border-radius: 24px;
    font-weight: 600;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.status-badge.active {
    background: var(--success);
}

.metric-card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px;
    border: 1px solid var(--border);
    transition: all 0.3s ease;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
    text-align: center;
    margin-bottom: 24px;
}

.metric-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
}

.metric-title {
    font-size: 15px;
    color: var(--text-secondary);
    font-weight: 600;
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.metric-value {
    font-size: 36px;
    font-weight: 700;
    color: var(--primary);
    line-height: 1.2;
}

.chart-container {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
    margin-bottom: 24px;
}

.control-card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 24px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
}

.control-card h4 {
    color: var(--primary);
    font-weight: 700;
    margin-bottom: 20px;
    border-bottom: 2px solid var(--border);
    padding-bottom: 12px;
}

.form-label {
    display: block;
    margin-bottom: 8px;
    font-weight: 600;
    color: var(--text-secondary);
}

.form-control {
    width: 100%;
    border-radius: 8px;
    border: 1px solid var(--border);
    padding: 12px;
    font-size: 15px;
    margin-bottom: 16px;
    transition: all 0.3s ease;
}

.form-control:focus {
    border-color: var(--primary);
    outline: none;
    box-shadow: 0 0 0 3px rgba(44, 82, 130, 0.2);
}

.btn {
    display: inline-block;
    font-weight: 600;
    text-align: center;
    vertical-align: middle;
    user-select: none;
    border: 1px solid transparent;
    padding: 12px 24px;
    font-size: 15px;
    border-radius: 8px;
    transition: all 0.3s ease;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
    width: 100%;
}

.btn:hover {
    transform: translateY(-2px);
}

.btn-primary {
    background-color: var(--primary);
    border-color: var(--primary);
    color: white;
}

.btn-primary:hover {
    background-color: var(--secondary);
    border-color: var(--secondary);
}

.btn-danger {
    background-color: var(--warning);
    border-color: var(--warning);
    color: white;
}

.btn-danger:hover {
    background-color: #c53030;
    border-color: #c53030;
}

.btn-success {
    background-color: var(--success);
    border-color: var(--success);
    color: white;
}

.btn-success:hover {
    background-color: #2f855a;
    border-color: #2f855a;
}

@media (max-width: 768px) {
    .col-md-3, .col-md-4, .col-md-12 {
        flex: 0 0 100%;
        max-width: 100%;
    }

    .dashboard {
        padding: 20px;
    }
    
    .header {
        flex-direction: column;
        text-align: center;
    }
    
    .header h1 {
        margin-bottom: 15px;
        font-size: 24px;
    }
    
    .metric-card, .chart-container, .control-card {
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
                <div id="systemStatus" class="status-badge">Disconnected</div>
            </div>
            <div class="row g-4">
                <div class="col-md-3"><div class="metric-card">
                    <div class="metric-title">Temperature</div>
                    <div id="temperature" class="metric-value">0°C</div>
                </div></div>
                <div class="col-md-3"><div class="metric-card">
                    <div class="metric-title">Humidity</div>
                    <div id="humidity" class="metric-value">0%</div>
                </div></div>
                <div class="col-md-3"><div class="metric-card">
                    <div class="metric-title">Speed</div>
                    <div id="speed" class="metric-value">0%</div>
                </div></div>
                <div class="col-md-3"><div class="metric-card">
                    <div class="metric-title">Time Remaining</div>
                    <div id="remaining" class="metric-value">0s</div>
                </div></div>
            </div>
            <div class="row g-4 mt-4">
                <div class="col-md-12"><div class="chart-container">
                    <canvas id="mainChart"></canvas>
                </div></div>
            </div>
            <div class="row g-4 mt-4">
                <div class="col-md-4"><div class="control-card">
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
                    <button id="stopButton" class="btn btn-danger w-100 mt-2" style="display: none;">Stop System</button>
                    <button id="downloadPdf" class="btn btn-primary w-100 mt-2" style="display: none;">Download Report</button>
                    <button id="startNewSession" class="btn btn-success w-100 mt-2" style="display: none;">New Session</button>
                </div></div>
            </div>
        </div>
    </div>
    <script>
        let mainChart;
        let hasDownloaded = false;
        let previousState = "disconnected";

        function initChart() {
            mainChart = new Chart(document.getElementById('mainChart').getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        { label: 'Temperature', data: [], borderColor: '#e53e3e', fill: false },
                        { label: 'Humidity', data: [], borderColor: '#3182ce', fill: false },
                        { label: 'Speed', data: [], borderColor: '#38a169', fill: false },
                        { label: 'Remaining', data: [], borderColor: '#805ad5', fill: false }
                    ]
                },
                options: {
                    responsive: true,
                    scales: { 
                        x: { title: { display: true, text: 'Time' }, ticks: { maxRotation: 45, minRotation: 45 } }, 
                        y: { beginAtZero: false } 
                    },
                    plugins: { legend: { position: 'top' } }
                }
            });
        }

        function updateChart(data) {
            const maxPoints = 20;
            const timestamps = data.history.timestamps.slice(-maxPoints);
            mainChart.data.labels = timestamps;
            mainChart.data.datasets[0].data = data.history.temperature.slice(-maxPoints);
            mainChart.data.datasets[1].data = data.history.humidity.slice(-maxPoints);
            mainChart.data.datasets[2].data = data.history.speed.slice(-maxPoints);
            mainChart.data.datasets[3].data = data.history.remaining.slice(-maxPoints);
            mainChart.update();
        }

        function resetChart() {
            mainChart.data.labels = [];
            mainChart.data.datasets.forEach(dataset => dataset.data = []);
            mainChart.update();
        }

        function updateSystemStatus(status, isActive = false) {
            const statusElement = document.getElementById('systemStatus');
            statusElement.textContent = status;
            statusElement.className = isActive ? 'status-badge active' : 'status-badge';
        }

        document.addEventListener('DOMContentLoaded', function() {
            initChart();
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
                    hasDownloaded = true;
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
                    hasDownloaded = false;
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
                const currentState = data.state;

                updateSystemStatus(currentState.charAt(0).toUpperCase() + currentState.slice(1), currentState === 'running');
                if (data.data_received) {
                    document.getElementById('temperature').textContent = `${data.temperature.toFixed(1)}°C`;
                    document.getElementById('humidity').textContent = `${data.humidity.toFixed(1)}%`;
                    document.getElementById('speed').textContent = `${data.speed}%`;
                    document.getElementById('remaining').textContent = `${data.remaining}s`;
                    updateChart(data);
                }

                if (currentState === 'disconnected') {
                    document.getElementById('temperature').textContent = `0°C`;
                    document.getElementById('humidity').textContent = `0%`;
                    document.getElementById('speed').textContent = `0%`;
                    document.getElementById('remaining').textContent = `0s`;
                    resetChart();
                }

                document.getElementById('stopButton').style.display = 
                    (currentState === 'running' || currentState === 'waiting' || currentState === 'ready') ? 'block' : 'none';
                document.getElementById('downloadPdf').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';
                document.getElementById('startNewSession').style.display = 
                    (currentState === 'stopped' && data.history.timestamps.length > 0) ? 'block' : 'none';

                if (currentState === 'stopped' && previousState !== 'stopped' && data.history.timestamps.length > 0 && !hasDownloaded) {
                    await downloadPdf();
                }

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

async def handle_data(request):
    global data, history, device_state, data_received, session_data
    
    if request.method == "POST":
        try:
            post_data = await request.json()
            status = post_data.get("status")
            logging.debug(f"Received POST data: {post_data}")

            if status == "data":
                required_fields = ['temperature', 'humidity', 'speed', 'remaining']
                if all(field in post_data for field in required_fields):
                    if not (isinstance(post_data["temperature"], (int, float)) and 
                            isinstance(post_data["humidity"], (int, float)) and 
                            isinstance(post_data["speed"], int) and 
                            isinstance(post_data["remaining"], int)):
                        logging.warning("Invalid data types in POST data")
                        return web.json_response({"error": "Invalid data types"}, status=400)

                    data_received = True
                    device_state = "running"
                    logging.info(f"State transitioned to: {device_state}")
                    
                    data.update({field: post_data[field] for field in required_fields})
                    
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    session_data.append({
                        "timestamp": timestamp,
                        **{k: post_data[k] for k in required_fields}
                    })
                    
                    for key in data:
                        history[key].append(data[key])
                        history[key] = history[key][-MAX_HISTORY:]
                    history["timestamps"].append(timestamp)
                    history["timestamps"] = history["timestamps"][-MAX_HISTORY:]
                    
                    logging.info(f"Received valid sensor data: {post_data}")
                    return web.json_response({"status": "success", "state": device_state})
                
                logging.warning("Missing fields in POST data")
                return web.json_response({"error": "Missing required fields"}, status=400)
            
            elif status == "arduino_ready":
                if device_state == "disconnected":
                    device_state = "ready"
                    logging.info(f"State transitioned to: {device_state}")
                return web.json_response({"status": "ready", "state": device_state})
            
            elif status == "check_auth":
                if auth_code is not None and runtime is not None:
                    logging.info(f"Sending auth_code: {auth_code}, runtime: {runtime}")
                    return web.json_response({
                        "status": "auth_code",
                        "code": auth_code,
                        "runtime": runtime,
                        "state": device_state
                    })
                logging.debug("No auth code yet or state not waiting, responding with current state")
                return web.json_response({"status": "waiting", "state": device_state})
            
            elif status == "start":
                device_state = "running"
                logging.info(f"State transitioned to: {device_state}")
                return web.json_response({"status": "running", "state": device_state})
            
            elif status == "stopped":
                device_state = "stopped"
                logging.info(f"State transitioned to: {device_state}")
                return web.json_response({"status": "stopped", "state": device_state})
                
        except json.JSONDecodeError:
            logging.error("Invalid JSON received")
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logging.error(f"Error processing data: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)
    
    return web.json_response({
        "state": device_state,
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "speed": data["speed"],
        "remaining": data["remaining"],
        "data_received": data_received,
        "history": history
    })

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
    global device_state, session_data, latest_pdf, auth_code, runtime, data, history, data_received
    
    try:
        device_state = "disconnected"
        if session_data:
            latest_pdf = generate_pdf(session_data)
            session_data = []
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        logging.info(f"System stopped, state and metrics reset - State: {device_state}")
        return web.json_response({"status": "stopped", "state": device_state})
        
    except Exception as e:
        logging.error(f"Error stopping system: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_reset(request):
    global device_state, session_data, latest_pdf, auth_code, runtime, data, history, data_received
    
    try:
        device_state = "disconnected"
        session_data = []
        latest_pdf = None
        auth_code = None
        runtime = None
        data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
        history = {"temperature": [], "humidity": [], "speed": [], "remaining": [], "timestamps": []}
        data_received = False
        logging.info(f"System reset for new session - State: {device_state}")
        return web.json_response({"status": "disconnected", "state": device_state})
        
    except Exception as e:
        logging.error(f"Error resetting system: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_pdf_download(request):
    global latest_pdf, session_data
    
    try:
        if not latest_pdf or not os.path.exists(latest_pdf):
            if session_data:
                latest_pdf = generate_pdf(session_data)
            else:
                logging.warning("No PDF or session data available for download")
                return web.json_response({"error": "No PDF available"}, status=404)
            
        response = web.FileResponse(latest_pdf)
        return response
        
    except Exception as e:
        logging.error(f"Error serving PDF: {e}")
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
