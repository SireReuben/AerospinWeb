import serial
import json
import asyncio
import logging
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

# Serial port configuration
SERIAL_PORT = '/dev/cu.usbserial-21130'  # Update this to your port
BAUD_RATE = 115200
PORT = 8080

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class SerialManager:
    def __init__(self, port, baud):
        self.port = port
        self.baud = baud
        self.instance = None
        self.lock = asyncio.Lock()

    async def get_instance(self):
        async with self.lock:
            if not self.instance or not self.instance.is_open:
                try:
                    self.instance = serial.Serial(self.port, self.baud, timeout=0.1)
                    logging.info("Serial port initialized")
                except serial.SerialException as e:
                    logging.error(f"Failed to open serial port: {e}")
                    raise
            return self.instance

    async def close(self):
        async with self.lock:
            if self.instance and self.instance.is_open:
                self.instance.close()
                logging.info("Serial port closed")


# Global variables
data = {"temperature": 0, "humidity": 0, "speed": 0, "remaining": 0}
history = {"temperature": [], "humidity": [], "speed": [], "timestamps": [], "remaining": []}
serial_manager = SerialManager(SERIAL_PORT, BAUD_RATE)
system_ready = False
data_received = False
auth_code = None
runtime = None
device_state = "disconnected"
session_data = []
latest_pdf = None


def generate_pdf(session_data):
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
    <title>Aerospin Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/remixicon@3.5.0/fonts/remixicon.css" rel="stylesheet">
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
            font-family: 'Poppins', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
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
                <h1><i class="ri-dashboard-3-line"></i> Aerospin Dashboard</h1>
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
                        <div class="control-header">
                            <h3>Device Setup</h3>
                        </div>
                        <div class="mb-3">
                            <label for="authCode">Auth Code (1-10):</label>
                            <input type="number" id="authCode" min="1" max="10" class="form-control" style="width: 100px;" required>
                        </div>
                        <div class="mb-3">
                            <label for="runtime">Runtime (seconds):</label>
                            <input type="number" id="runtime" min="1" class="form-control" style="width: 100px;" required>
                        </div>
                        <button id="submitSetup" class="btn btn-primary">Configure Device</button>
                        <button id="stopButton" class="btn btn-danger mt-2" style="display: none;">
                            <i class="ri-stop-circle-line"></i> Stop & Restart
                        </button>
                        <button id="downloadPdf" class="btn btn-primary mt-2" style="display: none;">Download Report</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        let tempChart, humidChart, speedChart, remainingChart;

        function initCharts() {
            const commonOptions = {
                responsive: true,
                maintainAspectRatio: false,
                scales: { x: { display: true, ticks: { maxRotation: 45, minRotation: 45 } }, y: { beginAtZero: false } },
                plugins: { legend: { display: false } }
            };
            tempChart = new Chart(document.getElementById('tempChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#f72585', fill: false }] },
                options: commonOptions
            });
            humidChart = new Chart(document.getElementById('humidChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#4cc9f0', fill: false }] },
                options: commonOptions
            });
            speedChart = new Chart(document.getElementById('speedChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#4361ee', fill: false }] },
                options: commonOptions
            });
            remainingChart = new Chart(document.getElementById('remainingChart').getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ data: [], borderColor: '#9b59b6', fill: false }] },
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

        function updateSystemStatus(status, isActive = false) {
            const statusElement = document.getElementById('systemStatus');
            statusElement.innerHTML = isActive ? '<i class="ri-checkbox-circle-line"></i> ' + status : '<i class="ri-focus-3-line"></i> ' + status;
            statusElement.className = isActive ? 'status-badge active' : 'status-badge';
        }

        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            document.getElementById('submitSetup').addEventListener('click', submitSetup);
            document.getElementById('stopButton').addEventListener('click', stopSystem);
            document.getElementById('downloadPdf').addEventListener('click', downloadPdf);
            setInterval(fetchData, 1000);
        });

        async function submitSetup() {
    const authCode = parseInt(document.getElementById('authCode').value);
    const runtime = parseInt(document.getElementById('runtime').value);
    console.log("Button clicked - Auth Code:", authCode, "Runtime:", runtime);
    if (isNaN(authCode) || authCode < 1 || authCode > 10) {
        console.error("Invalid auth code");
        alert("Auth code must be between 1 and 10.");
        return;
    }
    if (isNaN(runtime) || runtime < 1) {
        console.error("Invalid runtime");
        alert("Runtime must be a positive number.");
        return;
    }
    try {
        console.log("Sending POST to /setup");
        const response = await fetch('/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ authCode: authCode, runtime: runtime })
        });
        const result = await response.json();
        console.log("Server response:", result);
        if (result.status === 'waiting') {
            updateSystemStatus('Ready to Start');
            document.getElementById('submitSetup').disabled = true;
        } else {
            console.error("Unexpected response:", result);
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
                    // Force a page refresh to go back to connecting state
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

        async function fetchData() {
            try {
                const response = await fetch('/data');
                const data = await response.json();
                updateSystemStatus(data.state.charAt(0).toUpperCase() + data.state.slice(1), data.state === 'running');
                if (data.data_received) {
                    document.getElementById('temperature').innerHTML = `${data.temperature.toFixed(1)}<span class="metric-unit">°C</span>`;
                    document.getElementById('humidity').innerHTML = `${data.humidity.toFixed(1)}<span class="metric-unit">%</span>`;
                    document.getElementById('speed').innerHTML = `${data.speed}<span class="metric-unit">%</span>`;
                    document.getElementById('remaining').innerHTML = `${data.remaining}<span class="metric-unit">s</span>`;
                    updateCharts(data);

                    // Show/hide buttons based on state
                    document.getElementById('stopButton').style.display = 
                        (data.state === 'running' || data.state === 'waiting_code' || data.state === 'waiting') ? 'block' : 'none';
                    document.getElementById('downloadPdf').style.display = 
                        data.state === 'stopped' && data.history.timestamps.length > 0 ? 'block' : 'none';

                    // Auto-download PDF when stopped
                    if (data.state === 'stopped' && data.history.timestamps.length > 0) {
                        downloadPdf();
                    }
                }
            } catch (error) {
                console.error('Error fetching data:', error);
                updateSystemStatus('Connection Error');
            }
        }
    </script>
</body>
</html>
'''


async def read_serial_async():
    global data, history, system_ready, data_received, device_state, auth_code, runtime, session_data
    while True:
        try:
            serial_instance = await serial_manager.get_instance()
            line = await asyncio.to_thread(serial_instance.readline)
            if line:
                line_str = line.decode('utf-8').strip()
                logging.info(f"Received from ESP8266: {line_str}")
                try:
                    new_data = json.loads(line_str)
                    status = new_data.get("status")

                    if status == "arduino_ready":
                        await asyncio.to_thread(serial_instance.write, '{"status":"ready"}\n'.encode())
                        logging.info("Sent ready signal to ESP8266")
                    elif status == "ready_ack":
                        system_ready = True
                        device_state = "waiting_code"
                        logging.info("System ready, waiting for auth code")
                    elif status == "waiting":
                        device_state = "waiting"
                        logging.info("Device in waiting state")
                    elif status == "data":
                        data_received = True
                        device_state = "running"
                        data["temperature"] = new_data["temperature"]
                        data["humidity"] = new_data["humidity"]
                        data["speed"] = new_data["speed"]
                        data["remaining"] = new_data["remaining"]
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        session_data.append({
                            "timestamp": timestamp,
                            "temperature": data["temperature"],
                            "humidity": data["humidity"],
                            "speed": data["speed"],
                            "remaining": data["remaining"]
                        })
                        for key in data:
                            history[key].append(data[key])
                        history["timestamps"].append(timestamp)
                        if len(history["timestamps"]) > 20:
                            for key in history:
                                history[key] = history[key][-20:]
                        logging.info(f"Data updated: {data}")
                    elif status == "stopped":
                        device_state = "stopped"
                        data_received = False
                        if session_data:
                            global latest_pdf
                            latest_pdf = generate_pdf(session_data)
                        logging.info("Device stopped")
                except json.JSONDecodeError:
                    logging.warning(f"Invalid JSON received: {line_str}")
        except serial.SerialException as e:
            logging.error(f"Serial error: {e}")
            device_state = "disconnected"
            system_ready = False
            await asyncio.sleep(1)
        await asyncio.sleep(0.01)


async def handle_data(request):
    return web.json_response({
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "speed": data["speed"],
        "remaining": data["remaining"],
        "history": history,
        "data_received": data_received,
        "state": device_state
    })


async def handle_setup(request):
    global auth_code, runtime
    try:
        post_data = await request.json()
        logging.debug(f"Received setup data: {post_data}")  # Add this
        auth_code = post_data.get("authCode")
        runtime = post_data.get("runtime")
        if not (1 <= auth_code <= 10) or runtime < 1:
            return web.json_response({"error": "Invalid auth code or runtime"}, status=400)
        serial_instance = await serial_manager.get_instance()
        await asyncio.to_thread(serial_instance.write, json.dumps(
            {"status": "auth_code", "code": auth_code, "runtime": runtime}).encode() + b'\n')
        logging.info(f"Sent auth code {auth_code} and runtime {runtime} to ESP8266")
        return web.json_response({"status": "waiting"})
    except Exception as e:
        logging.error(f"Error in handle_setup: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_start(request):
    try:
        serial_instance = await serial_manager.get_instance()
        await asyncio.to_thread(serial_instance.write, '{"status":"start"}\n'.encode())
        logging.info("Sent start command to ESP8266")
        return web.json_response({"status": "running"})
    except Exception as e:
        logging.error(f"Error in handle_start: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_stop(request):
    global device_state, session_data, latest_pdf
    try:
        serial_instance = await serial_manager.get_instance()
        await asyncio.to_thread(serial_instance.write, '{"status":"stop"}\n'.encode())
        logging.info("Sent stop command to ESP8266")

        # Generate PDF immediately when stopped
        if session_data:
            latest_pdf = generate_pdf(session_data)

        device_state = "disconnected"
        session_data = []
        return web.json_response({"status": "stopped"})
    except Exception as e:
        logging.error(f"Error in handle_stop: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_pdf_download(request):
    global latest_pdf, session_data
    if not latest_pdf and session_data:
        latest_pdf = generate_pdf(session_data)
    if not latest_pdf:
        return web.json_response({"error": "No PDF available"}, status=404)
    return web.FileResponse(latest_pdf)


async def init_app():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text=HTML_CONTENT, content_type='text/html'))
    app.router.add_get('/data', handle_data)
    app.router.add_post('/setup', handle_setup)
    app.router.add_post('/start', handle_start)
    app.router.add_post('/stop', handle_stop)
    app.router.add_get('/download_pdf', handle_pdf_download)
    return app


async def main():
    global serial_manager
    try:
        await serial_manager.get_instance()
        asyncio.create_task(read_serial_async())
        app = await init_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logging.info(f"Server started at http://localhost:{PORT}")
        while True:
            await asyncio.sleep(10)
    except Exception as e:
        logging.error(f"Main loop error: {e}")
        await serial_manager.close()


if __name__ == "__main__":
    asyncio.run(main())