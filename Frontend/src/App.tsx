import { useState, useEffect, useRef } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { AlertCircle, CheckCircle2, Activity, Bot, Wrench, ClipboardList, RefreshCcw, Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

const API_BASE = window.location.hostname === 'localhost' 
  ? 'http://localhost:8000' 
  : `http://${window.location.hostname}:8000`

const WS_BASE = window.location.hostname === 'localhost'
  ? 'ws://localhost:8000'
  : `ws://${window.location.hostname}:8000`

interface SensorData {
  machine_id: string;
  timestamp: number;
  vibration: number;
  volt: number;
  pressure: number;
  rotate: number;
  is_anomaly: boolean;
  rul?: number;
  rul_hours?: number;
  rul_years?: number;
  rul_days?: number;
  rul_hrs?: number;
  rul_display?: string;
  health_pct?: number | null;
  prediction_status?: string;
  trend_warnings?: {parameter: string; message: string; severity: string; prediction: string}[];
  health_alert?: {level: string; message: string; health_pct: number} | null;
  maintenance_due?: string | null;
  days_to_maintenance?: number | null;
  degradation_rate?: number;
}

interface WorkOrder {
  id: number;
  machine_id: string;
  fault_type: string;
  severity: string;
  recommended_action: string;
  explanation: string;
  status: string;
  created_at: string;
}

interface AgentActivity {
  timestamp: number;
  step: string;
  detail: string;
  status: string;
}

function App() {
  const [data, setData] = useState<SensorData[]>([])
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isAnomaly, setIsAnomaly] = useState(false)
  const [rightTab, setRightTab] = useState<'chat' | 'agent'>('chat')
  const [agentActivity, setAgentActivity] = useState<AgentActivity[]>([])
  
  const [chatMessages, setChatMessages] = useState<{sender: 'user'|'agent', text: string}[]>([
    {sender: 'agent', text: `👋 Hello! I'm your **AI Maintenance Assistant** powered by Claude Haiku 4.5.\n\nI can help you with:\n- Real-time machine health analysis\n- Fault diagnosis and root cause\n- Maintenance scheduling\n- Sensor data interpretation\n\nAsk me anything about the compressor!`}
  ])
  const [chatInput, setChatInput] = useState('')
  const [isChatLoading, setIsChatLoading] = useState(false)
  const activityRef = useRef<HTMLDivElement>(null)

  const maxDataPoints = 30;

  const fetchWorkOrders = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/work-orders`)
      const json = await res.json()
      setWorkOrders(json)
    } catch (e) {
      console.error(e)
    }
  }

  const fetchAgentActivity = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/activity`)
      const json = await res.json()
      setAgentActivity(json.activity || [])
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchWorkOrders()
    fetchAgentActivity()

    // Poll agent activity every 3 seconds
    const activityInterval = setInterval(fetchAgentActivity, 3000)

    const ws = new WebSocket(`${WS_BASE}/ws/sensors`)

    ws.onopen = () => {
      setIsConnected(true)
    }

    ws.onmessage = (event) => {
      const reading: SensorData = JSON.parse(event.data)
      
      setData(prevData => {
        const newData = [...prevData, reading]
        if (newData.length > maxDataPoints) {
          return newData.slice(newData.length - maxDataPoints)
        }
        return newData
      })

      if (reading.is_anomaly && !isAnomaly) {
        setIsAnomaly(true)
        setRightTab('agent') // Auto-switch to agent tab on anomaly
        setTimeout(fetchWorkOrders, 3000)
        setTimeout(fetchAgentActivity, 2000)
      } else if (!reading.is_anomaly && isAnomaly) {
        setIsAnomaly(false)
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
    }

    return () => {
      ws.close()
      clearInterval(activityInterval)
    }
  }, [isAnomaly])

  // Auto-scroll agent activity
  useEffect(() => {
    if (activityRef.current) {
      activityRef.current.scrollTop = activityRef.current.scrollHeight
    }
  }, [agentActivity])

  const triggerAnomaly = async () => {
    try {
      await fetch(`${API_BASE}/api/trigger-anomaly`, { method: 'POST' })
      setRightTab('agent')
      setTimeout(fetchWorkOrders, 4000)
      setTimeout(fetchWorkOrders, 8000)
      setTimeout(fetchAgentActivity, 2000)
      setTimeout(fetchAgentActivity, 5000)
    } catch (e) {
      console.error(e)
    }
  }

  const resetAnomaly = async () => {
    try {
      await fetch(`${API_BASE}/api/reset-anomaly`, { method: 'POST' })
      setIsAnomaly(false)
      fetchWorkOrders()
    } catch (e) {
      console.error(e)
    }
  }

  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!chatInput.trim()) return

    const userMessage = chatInput
    setChatMessages(prev => [...prev, { sender: 'user', text: userMessage }])
    setChatInput('')
    setIsChatLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: userMessage })
      })
      const responseData = await res.json()
      setChatMessages(prev => [...prev, { sender: 'agent', text: responseData.response || 'No response.' }])
    } catch (e) {
      console.error(e)
      setChatMessages(prev => [...prev, { sender: 'agent', text: `Error connecting to AI agent.` }])
    } finally {
      setIsChatLoading(false)
    }
  }

  const formatTime = (unixTime: number) => {
    const date = new Date(unixTime * 1000)
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
  }

  const formatActivityTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`
  }

  const latestReading = data.length > 0 ? data[data.length - 1] : null

  // Parse recommended action into visual workflow steps
  const parseWorkflowSteps = (action: string): string[] => {
    if (!action) return ['No action specified']
    // Remove prefix tags
    let clean = action.replace(/^\[(AUTO-FIXED|REQUIRES HUMAN)\]\s*/i, '')
    // Try splitting by common patterns
    const steps = clean
      .split(/(?:\.\s+(?=[A-Z]))|(?:\d+\.\s+)|(?:;\s+)/)
      .map(s => s.trim())
      .filter(s => s.length > 5)
    if (steps.length <= 1) {
      // Fallback: split long text into chunks
      const words = clean.split(' ')
      const chunks: string[] = []
      for (let i = 0; i < words.length; i += 12) {
        chunks.push(words.slice(i, i + 12).join(' '))
      }
      return chunks.slice(0, 5)
    }
    return steps.slice(0, 6) // max 6 steps for visual clarity
  }

  // Calculate component health from sensor readings
  const getPartsHealth = (reading: SensorData) => {
    const v   = reading.volt ?? 170
    const r   = reading.rotate ?? 450
    const p   = reading.pressure ?? 100
    const vib = reading.vibration ?? 40

    const clamp = (val: number) => Math.max(0, Math.min(100, Math.round(val)))
    const getColor = (h: number) => h > 70 ? '#2D6A4F' : h > 40 ? '#B48400' : '#DC2626'
    const getStatus = (h: number, good: string, warn: string, bad: string) => 
      h > 70 ? good : h > 40 ? warn : bad

    // Motor Health — voltage deviation + rotation
    const motorHealth = clamp(100 - (Math.abs(v - 170) / 130) * 60 - (Math.abs(r - 450) / 1500) * 40)
    // Bearing Health — vibration is the primary indicator
    const bearingHealth = clamp(100 - (Math.max(0, vib - 30) / 70) * 100)
    // Compressor Element — pressure + rotation + vibration
    const compressorHealth = clamp(100 - (Math.abs(p - 100) / 100) * 50 - (Math.abs(r - 450) / 1500) * 30 - (Math.max(0, vib - 40) / 60) * 20)
    // Electrical System — voltage stability
    const electricalHealth = clamp(100 - (Math.abs(v - 170) / 130) * 100)
    // Oil Circuit — pressure + vibration
    const oilHealth = clamp(100 - (Math.max(0, p - 120) / 80) * 50 - (Math.max(0, vib - 50) / 50) * 50)

    return [
      { name: 'Motor', icon: '⚡', health: motorHealth, color: getColor(motorHealth), status: getStatus(motorHealth, 'Operating normally', 'Voltage stress detected', 'Motor overload — inspect windings') },
      { name: 'Bearings', icon: '🔩', health: bearingHealth, color: getColor(bearingHealth), status: getStatus(bearingHealth, 'Low vibration — healthy', 'Vibration increasing — monitor', 'High vibration — replace bearings') },
      { name: 'Compressor Element', icon: '🌀', health: compressorHealth, color: getColor(compressorHealth), status: getStatus(compressorHealth, 'Compression normal', 'Efficiency declining', 'Screw element degraded') },
      { name: 'Electrical', icon: '🔌', health: electricalHealth, color: getColor(electricalHealth), status: getStatus(electricalHealth, 'Supply voltage stable', 'Voltage drifting', 'Voltage critical — check supply') },
      { name: 'Oil Circuit', icon: '🛢️', health: oilHealth, color: getColor(oilHealth), status: getStatus(oilHealth, 'Oil pressure normal', 'Oil flow restricted', 'Oil system failure — check separator') },
    ]
  }

  const ChartCard = ({ title, dataKey, color }: { title: string, dataKey: keyof SensorData, color: string }) => (
    <div className={`chart-card-container ${isAnomaly ? 'anomaly' : ''}`}>
      <h3 className="chart-card-title">{title}</h3>
      <div style={{ flex: 1, width: '100%', minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} syncId="machineData">
            <CartesianGrid strokeDasharray="3 3" stroke="#E8DDD0" vertical={false} />
            <XAxis 
              dataKey="timestamp" 
              tickFormatter={formatTime} 
              stroke="#7A6A58" 
              tick={{fontSize: 12, fill: '#7A6A58'}} 
              axisLine={false}
              tickLine={false}
              dy={10}
            />
            <YAxis 
              stroke="#7A6A58" 
              tick={{fontSize: 12, fill: '#7A6A58'}} 
              domain={['auto', 'auto']} 
              axisLine={false}
              tickLine={false}
              dx={-10}
            />
            <Tooltip 
              contentStyle={{ 
                backgroundColor: '#FFFFFF', 
                border: '1px solid #E8DDD0', 
                borderRadius: '10px',
                boxShadow: '0 4px 16px rgba(180, 150, 120, 0.1)',
                color: '#2C2416'
              }} 
              labelFormatter={(label) => formatTime(label as number)} 
            />
            <Line 
              type="monotone" 
              dataKey={dataKey} 
              stroke={color} 
              strokeWidth={1.5} 
              dot={false} 
              isAnimationActive={false} 
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )

  return (
    <div className={`app-root ${isAnomaly ? 'anomaly-active' : ''}`}>
      {isAnomaly && <div className="anomaly-overlay" />}
      
      {/* Header */}
      <header className="app-header">
        <h1 className="app-title">
          <Activity size={28} color="#C8956C" strokeWidth={2.5} />
          MachineWhisperer
        </h1>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ fontSize: '12px', color: '#A98C78', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Zap size={14} />
            Claude Haiku 4.5 + LangGraph
          </div>
          <div style={{ padding: '8px 16px', borderRadius: '9999px', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '14px', fontWeight: 500, backgroundColor: isConnected ? '#F2EDE4' : '#FFF0E8', color: isConnected ? '#8B6F5E' : '#9E3E15' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: isConnected ? '#C8956C' : '#D35400', animation: isConnected ? 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' : 'none' }}></div>
            {isConnected ? 'Sensors Online' : 'Sensors Offline'}
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="app-main">
        
        {/* Left panel */}
        <div className="left-panel custom-scrollbar">

          {/* Status Card */}
          <div style={{ gridColumn: '1 / -1', background: '#FFFFFF', border: '1px solid #E8DDD0', borderLeft: `3px solid ${isAnomaly ? '#D35400' : latestReading?.prediction_status === 'critical' ? '#D35400' : latestReading?.prediction_status === 'warning' ? '#B48400' : latestReading?.prediction_status === 'degrading' ? '#92700C' : '#C8956C'}`, borderRadius: '16px', padding: '24px 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
              <div style={{ width: '40px', height: '40px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: isAnomaly ? '#FFF0E8' : latestReading?.prediction_status === 'critical' ? '#FFF0E8' : latestReading?.prediction_status === 'warning' ? '#FFF9E8' : latestReading?.prediction_status === 'degrading' ? '#FFFBE8' : '#F2EDE4', color: isAnomaly ? '#D35400' : latestReading?.prediction_status === 'critical' ? '#D35400' : latestReading?.prediction_status === 'warning' ? '#B48400' : latestReading?.prediction_status === 'degrading' ? '#92700C' : '#8B6F5E' }}>
                {isAnomaly || latestReading?.prediction_status === 'critical' || latestReading?.prediction_status === 'warning' ? <AlertCircle size={20} strokeWidth={2.5} /> : <CheckCircle2 size={20} strokeWidth={2.5} />}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '26px', fontWeight: 500, color: '#2C2416', margin: '0 0 4px 0' }}>
                  {isAnomaly ? 'Anomaly Detected' 
                    : latestReading?.prediction_status === 'critical' ? '⚠️ Critical Degradation'
                    : latestReading?.prediction_status === 'warning' ? '⚠️ Predictive Warning'
                    : latestReading?.prediction_status === 'degrading' ? '📉 Degradation Detected'
                    : 'All Systems Nominal'}
                </h2>
                <p style={{ color: '#7A6A58', fontSize: '15px', margin: 0 }}>
                  {isAnomaly ? 'AI Agent is diagnosing the fault and generating a work order...' 
                    : latestReading?.prediction_status === 'critical' ? `Health at ${latestReading?.health_pct}% — failure predicted. Maintenance due: ${latestReading?.maintenance_due || 'calculating...'}`
                    : latestReading?.prediction_status === 'warning' ? `Health declining. Schedule maintenance within ${latestReading?.days_to_maintenance || '?'} days.`
                    : latestReading?.prediction_status === 'degrading' ? 'Early degradation trend detected. AI monitoring closely.'
                    : 'Machine operating within normal parameters. AI predictive monitoring active.'}
                </p>
                {latestReading?.trend_warnings && latestReading.trend_warnings.length > 0 && !isAnomaly && (
                  <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {latestReading.trend_warnings.slice(0, 2).map((w, i) => (
                      <div key={i} style={{ fontSize: '12px', color: w.severity === 'warning' ? '#C9622F' : '#92700C', background: w.severity === 'warning' ? '#FFF0E8' : '#FFFBE8', padding: '4px 10px', borderRadius: '6px' }}>
                        📊 {w.message} → <em>{w.prediction}</em>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button 
                  onClick={triggerAnomaly} 
                  className="active:scale-95 active:brightness-90 active:shadow-inner transition-all duration-150 active:ring-4 active:ring-[#C8956C]/50 focus:outline-none"
                  style={{ background: '#C8956C', color: 'white', borderRadius: '8px', padding: '12px 28px', fontWeight: 500, fontSize: '15px', border: 'none', cursor: 'pointer' }}>
                  ⚡ Simulate Fault
                </button>
                <button 
                  onClick={resetAnomaly} 
                  className="active:scale-95 active:brightness-90 active:shadow-inner transition-all duration-150 active:ring-4 active:ring-[#C8956C]/50 focus:outline-none"
                  style={{ background: 'transparent', border: '1.5px solid #C8956C', color: '#C8956C', borderRadius: '8px', padding: '12px 28px', fontWeight: 500, fontSize: '15px', cursor: 'pointer' }}>
                  Reset
                </button>
              </div>

              {latestReading && latestReading.rul_years !== undefined && latestReading.health_pct !== null && latestReading.health_pct !== undefined && (
                <div style={{ background: '#FAF8F4', border: '1px solid #E0D5C8', borderRadius: '16px', padding: '20px 32px', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginLeft: '16px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#7A6A58', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Remaining Useful Life</span>
                  <div style={{ fontSize: '32px', fontWeight: 300, color: '#2C2416', lineHeight: 1.2, display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                    <span style={{ fontWeight: 600 }}>{latestReading.rul_years ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>yr</span>
                    <span style={{ fontWeight: 600, marginLeft: '4px' }}>{latestReading.rul_days ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>days</span>
                    <span style={{ fontWeight: 600, marginLeft: '4px' }}>{latestReading.rul_hrs ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>hrs</span>
                  </div>
                  <div style={{ marginTop: '8px', width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ fontSize: '11px', color: '#7A6A58' }}>Machine Health</span>
                      <span style={{ fontSize: '11px', fontWeight: 600, color: (latestReading.health_pct ?? 0) > 50 ? '#2D6A4F' : (latestReading.health_pct ?? 0) > 20 ? '#C9622F' : '#DC2626' }}>{latestReading.health_pct}%</span>
                    </div>
                    <div style={{ height: '6px', background: '#E8E2D9', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${latestReading.health_pct ?? 0}%`, background: (latestReading.health_pct ?? 0) > 50 ? '#2D6A4F' : (latestReading.health_pct ?? 0) > 20 ? '#C9622F' : '#DC2626', borderRadius: '3px', transition: 'width 1s ease' }}></div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
          
          <ChartCard title="Vibration (mm/s)" dataKey="vibration" color="#C8956C" />
          <ChartCard title="Voltage (V)" dataKey="volt" color="#8B6F5E" />
          <ChartCard title="Pressure (psi)" dataKey="pressure" color="#A98C78" />
          <ChartCard title="Rotation (RPM)" dataKey="rotate" color="#D4A373" />

          {/* Parts Health Panel */}
          {latestReading && (
            <div style={{ gridColumn: '1 / -1', background: '#FFFFFF', border: '1px solid #E8DDD0', borderRadius: '16px', padding: '24px 28px' }}>
              <h3 style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7A6A58', marginBottom: '16px' }}>⚙️ Component Health Monitor</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
                {getPartsHealth(latestReading).map((part, i) => (
                  <div key={i} style={{ background: '#FAF8F4', border: `1px solid ${part.color}22`, borderLeft: `3px solid ${part.color}`, borderRadius: '10px', padding: '14px 16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: '#2C2416' }}>{part.icon} {part.name}</span>
                      <span style={{ fontSize: '11px', fontWeight: 700, color: part.color }}>{part.health}%</span>
                    </div>
                    <div style={{ height: '5px', background: '#E8E2D9', borderRadius: '3px', overflow: 'hidden', marginBottom: '6px' }}>
                      <div style={{ height: '100%', width: `${part.health}%`, background: part.color, borderRadius: '3px', transition: 'width 1s ease' }} />
                    </div>
                    <div style={{ fontSize: '11px', color: '#7A6A58' }}>{part.status}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Work Orders */}
          <div className="work-order-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 className="work-order-section-title">
                <ClipboardList size={22} color="#C8956C" />
                AI-Generated Maintenance Orders
              </h2>
              <button 
                onClick={fetchWorkOrders}
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#8B6F5E', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px' }}
              >
                <RefreshCcw size={16} />
                Refresh
              </button>
            </div>
            
            {workOrders.length === 0 ? (
              <div style={{ background: '#FFFFFF', border: '1px dashed #E8DDD0', borderRadius: '16px', padding: '40px', textAlign: 'center', color: '#A98C78' }}>
                No active work orders. AI agent is monitoring — will auto-generate on fault detection.
              </div>
            ) : (
              <div className="work-order-grid">
                {workOrders.map(wo => (
                  <div key={wo.id} className="work-order-card">
                    <div className="wo-header">
                      <h3 className="wo-type">{wo.fault_type}</h3>
                      <span className={`wo-severity severity-${wo.severity.toLowerCase()}`}>
                        {wo.severity}
                      </span>
                    </div>
                    <p className="wo-explanation">{wo.explanation?.substring(0, 200)}{wo.explanation?.length > 200 ? '...' : ''}</p>
                    
                    <div className="wo-action-box">
                      <span className="wo-action-label">Recommended Action</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Wrench size={14} color="#C8956C" />
                        <span className="wo-action-text">{wo.recommended_action}</span>
                      </div>
                    </div>

                    <div className="wo-footer">
                      <span>{wo.machine_id}</span>
                      <span>{new Date(wo.created_at).toLocaleTimeString()}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right panel — tabbed */}
        <div className="right-panel">
          {/* Tab switcher */}
          <div className="tab-switcher">
            <button className={`tab-btn ${rightTab === 'chat' ? 'active' : ''}`} onClick={() => setRightTab('chat')}>
              <Bot size={16} /> AI Chat
            </button>
            <button className={`tab-btn ${rightTab === 'agent' ? 'active' : ''}`} onClick={() => setRightTab('agent')}>
              <Zap size={16} /> Agent Activity
              {agentActivity.length > 0 && (
                <span style={{ background: '#C8956C', color: 'white', borderRadius: '9999px', fontSize: '10px', padding: '2px 6px', marginLeft: '4px' }}>
                  {agentActivity.length}
                </span>
              )}
            </button>
          </div>

          {/* Chat Tab */}
          {rightTab === 'chat' && (
            <>
              <div className="chat-messages custom-scrollbar">
                {chatMessages.map((msg, i) => (
                  <div key={i} className={msg.sender === 'user' ? 'user-bubble' : 'ai-bubble'}>
                    {msg.sender === 'user' ? (
                      msg.text
                    ) : (
                      <ReactMarkdown>{msg.text}</ReactMarkdown>
                    )}
                  </div>
                ))}
                {isChatLoading && (
                  <div className="ai-bubble" style={{ opacity: 0.7 }}>
                    <span style={{ display: 'inline-flex', gap: '4px' }}>
                      <span style={{ animation: 'pulse 1s infinite' }}>●</span>
                      <span style={{ animation: 'pulse 1s infinite 0.2s' }}>●</span>
                      <span style={{ animation: 'pulse 1s infinite 0.4s' }}>●</span>
                    </span>
                    {' '}Analyzing with Claude Haiku 4.5...
                  </div>
                )}
              </div>
              
              <form onSubmit={handleSendChat} className="chat-input-bar">
                <input 
                  type="text" 
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  placeholder="Ask about the machine..."
                  className="chat-input-field"
                />
                <button 
                  type="submit" 
                  disabled={isChatLoading || !chatInput.trim()}
                  className="chat-send-btn"
                >
                  →
                </button>
              </form>
            </>
          )}

          {/* Agent Activity Tab */}
          {rightTab === 'agent' && (
            <div className="agent-activity-feed custom-scrollbar" ref={activityRef}>
              {agentActivity.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#A98C78', padding: '40px 20px', fontSize: '14px' }}>
                  <Zap size={32} color="#E8DDD0" style={{ margin: '0 auto 12px' }} />
                  <p>No agent activity yet.</p>
                  <p style={{ fontSize: '12px' }}>Click <strong>"Simulate Fault"</strong> to see the AI agent in action.</p>
                </div>
              ) : (
                agentActivity.map((entry, i) => (
                  <div key={i} className={`activity-entry ${entry.status}`}>
                    <div>
                      <span className="activity-time">{formatActivityTime(entry.timestamp)}</span>
                    </div>
                    <div>
                      <div className="activity-step">{entry.step}</div>
                      <div className="activity-detail">{entry.detail}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

      </main>
    </div>
  )
}

export default App
