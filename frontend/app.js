const { useState, useEffect, useRef } = React;

const App = () => {
    const [tasks, setTasks] = useState([]);
    const [description, setDescription] = useState('');
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [message, setMessage] = useState(null);
    const [dragActive, setDragActive] = useState(false);
    const [wsStatus, setWsStatus] = useState('Connecting...');
    const [tooltip, setTooltip] = useState({ show: false, taskId: null, message: '', x: 0, y: 0 });

    const wsRef = useRef(null);
    const reconnectAttemptRef = useRef(0);

    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    const showTooltip = (e, taskId, message) => {
        const rect = e.target.getBoundingClientRect();
        setTooltip({
            show: true,
            taskId,
            message,
            x: rect.left + rect.width / 2,
            y: rect.top - 10
        });
    };

    const hideTooltip = () => {
        setTooltip({ show: false, taskId: null, message: '', x: 0, y: 0 });
    };

    const connectWebSocket = async () => {
        while(true) {
            const ws = new WebSocket(`ws://${window.location.host}/ws`);
            wsRef.current = ws;

            const connected = await new Promise((resolve) => {
                ws.onopen = () => {
                    console.log('WebSocket connected');
                    setWsStatus('Connected');
                    reconnectAttemptRef.current = 0;
                    resolve(true);
                };

                ws.onerror = () => resolve(false);
            });

            if (connected) {
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);

                    if (data.type === 'initial_tasks') {
                        // Receive initial 100 tasks
                        setTasks(data.tasks || []);
                    } else if (data.type === 'task_update') {
                        // Update existing task by ID
                        setTasks(prevTasks =>
                            prevTasks.map(task =>
                                task.id === data.task.id ? data.task : task
                            )
                        );
                    } else if (data.type === 'new_task') {
                        // Add new task to the beginning
                        setTasks(prevTasks => [data.task, ...prevTasks.slice(0, 99)]);
                    }
                };

                await new Promise(resolve => {
                    ws.onclose = (event) => {
                        console.log('WebSocket disconnected', event.code, event.reason);
                        setWsStatus('Offline');
                        resolve();
                    };
                });
            } else {
               // Show countdown and wait
                const delays = [5, 10, 30, 60];
                const delay = delays[Math.min(reconnectAttemptRef.current, delays.length - 1)];
                setWsStatus('Offline');
                for (let i = delay; i > 0; i--) {
                    setWsStatus(`Reconnecting in ${i}s...`);
                    await sleep(1000);
                }

                setWsStatus(`Reconnecting now`);
                reconnectAttemptRef.current += 1;
            }
        }
    };

    // Initialize WebSocket connection
    useEffect(() => {
        connectWebSocket();

        // Cleanup on unmount
        return () => {
            if (wsRef.current)
                wsRef.current.close();
        };
    }, []);

    // File upload
    const handleUpload = async (e) => {
        e.preventDefault();
        if (!file || !description) return;

        setUploading(true);
        setMessage(null);

        const formData = new FormData();
        formData.append('file', file);
        formData.append('description', description);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();

            if (response.ok) {
                setMessage({ type: 'success', text: `✅ Upload successful! Task ID: ${result.task_id}` });
                setDescription('');
                setFile(null);
                document.getElementById('fileInput').value = '';
                // WebSocket will automatically send the new task
            } else {
                setMessage({ type: 'error', text: `❌ ${result.detail}` });
            }
        } catch (error) {
            setMessage({ type: 'error', text: '❌ Upload failed' });
        } finally {
            setUploading(false);
        }
    };

    // Drag & drop
    const handleDrop = (e) => {
        e.preventDefault();
        setDragActive(false);
        const files = e.dataTransfer.files;
        if (files[0] && files[0].type === 'application/pdf') {
            setFile(files[0]);
        } else {
            setMessage({ type: 'error', text: '❌ Please upload PDF files only' });
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'PENDING': return 'bg-yellow-100 text-yellow-800';
            case 'RUNNING': return 'bg-blue-100 text-blue-800';
            case 'COMPLETED': return 'bg-green-100 text-green-800';
            case 'FAILED': return 'bg-red-100 text-red-800';
            default: return 'bg-gray-100 text-gray-800';
        }
    };

    const getWsStatusColor = (status) => {
        if (status === 'Connected') return 'text-green-600';
        if (status === 'Connecting...') return 'text-yellow-600';
        return 'text-red-600'; // Offline states
    };

    const getWsIcon = (status) => {
        if (status === 'Connected') return '🟢';
        if (status === 'Connecting...') return '🟡';
        return '🔴'; // Offline states
    };

    return (
        <div className="min-h-screen bg-gray-100 p-4">
            <div className="max-w-6xl mx-auto">
                <div className="flex justify-between items-center mb-8">
                    <h1 className="text-4xl font-bold text-gray-800">🔍 PDF Scanner</h1>
                    <div className={`text-sm font-medium ${getWsStatusColor(wsStatus)}`}>
                        {getWsIcon(wsStatus)} {wsStatus}
                    </div>
                </div>

                {/* Upload Section */}
                <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                    <h2 className="text-2xl font-bold mb-4">Upload PDF</h2>

                    <form onSubmit={handleUpload} className="space-y-4">
                        <input
                            type="text"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="Enter description"
                            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                            required
                        />

                        <div
                            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                                dragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
                            }`}
                            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                            onDragLeave={() => setDragActive(false)}
                            onDrop={handleDrop}
                            onClick={() => document.getElementById('fileInput').click()}
                        >
                            <div className="cursor-pointer">
                                {file ? (
                                    <p className="text-green-600 font-medium">{file.name}</p>
                                ) : (
                                    <>
                                        <svg className="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 48 48">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02" />
                                        </svg>
                                        <p className="text-gray-600">Drop PDF file here or click to browse</p>
                                        <p className="text-sm text-gray-500 mt-1">PDF files only, up to 50MB</p>
                                    </>
                                )}
                            </div>
                            <input
                                id="fileInput"
                                type="file"
                                accept=".pdf"
                                onChange={(e) => setFile(e.target.files[0])}
                                className="hidden"
                            />
                        </div>

                        {message && (
                            <div className={`p-4 rounded-lg ${
                                message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                            }`}>
                                {message.text}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={uploading || !file || !description}
                            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white font-medium py-3 px-6 rounded-lg transition-colors"
                        >
                            {uploading ? '⏳ Uploading...' : '🚀 Upload & Scan'}
                        </button>
                    </form>
                </div>

                {/* Tasks Table */}
                <div className="bg-white rounded-lg shadow-md">
                    <div className="p-6 border-b">
                        <h2 className="text-2xl font-bold">Scan Results</h2>
                        <p className="text-sm text-gray-500 mt-1">Real-time updates via WebSocket • Showing {tasks.length} tasks</p>
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Filename</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {tasks.length === 0 ? (
                                    <tr>
                                        <td colSpan="6" className="px-6 py-12 text-center text-gray-500">
                                            {wsStatus === 'Connected' ? 'No scans found. Upload a PDF to get started!' : 'Connecting to server...'}
                                        </td>
                                    </tr>
                                ) : (
                                    tasks.map(task => (
                                        <tr key={task.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4 font-medium">#{task.id}</td>
                                            <td className="px-6 py-4">{task.description}</td>
                                            <td className="px-6 py-4">{task.filename}</td>
                                            <td className="px-6 py-4">
                                                <span
                                                    className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(task.status)} ${
                                                        task.status === 'FAILED' && task.error_message ? 'cursor-pointer' : ''
                                                    }`}
                                                    onMouseEnter={(e) => {
                                                        if (task.status === 'FAILED' && task.error_message) {
                                                            showTooltip(e, task.id, task.error_message);
                                                        }
                                                    }}
                                                    onMouseLeave={hideTooltip}
                                                >
                                                    {task.status}
                                                    {task.status === 'FAILED' && ' ⚠️'}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-500">
                                                {new Date(task.created_at).toLocaleString()}
                                            </td>
                                            <td className="px-6 py-4 text-sm space-x-2">
                                                {task.status === 'COMPLETED' && (
                                                    <>
                                                        <a href={`/scan-results/${task.id}`} className="text-blue-600 hover:text-blue-800">
                                                            📄 View Results
                                                        </a>
                                                        {task.report_url && (
                                                            <a href={task.report_url} download className="text-green-600 hover:text-green-800">
                                                                💾 Download
                                                            </a>
                                                        )}
                                                        {task.virustotal_url && (
                                                            <a href={task.virustotal_url} target="_blank" rel="noopener noreferrer" className="text-purple-600 hover:text-purple-800">
                                                                🔗 VirusTotal
                                                            </a>
                                                        )}
                                                    </>
                                                )}
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Custom Tooltip */}
                {tooltip.show && (
                    <div
                        className="fixed z-50 bg-gray-900 text-white text-sm rounded-lg p-3 max-w-xs shadow-lg pointer-events-none"
                        style={{
                            left: tooltip.x,
                            top: tooltip.y,
                            transform: 'translateX(-50%) translateY(-100%)'
                        }}
                    >
                        <div className="break-words">{tooltip.message}</div>
                        <div
                            className="absolute top-full left-1/2 transform -translate-x-1/2 w-2 h-2 bg-gray-900 rotate-45"
                            style={{ marginTop: '-4px' }}
                        ></div>
                    </div>
                )}
            </div>
        </div>
    );
};

// Render the app
ReactDOM.render(<App />, document.getElementById('root'));