import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { AlertCircle, CheckCircle2, Activity, Bot, Wrench, ClipboardList, RefreshCcw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

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
  health_pct?: number;
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

function App() {
  const [data, setData] = useState<SensorData[]>([])
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isAnomaly, setIsAnomaly] = useState(false)
  
  const [chatMessages, setChatMessages] = useState<{sender: 'user'|'agent', text: string}[]>([
    {sender: 'agent', text: 'Hello! I am your AI maintenance assistant. How can I help you today?'}
  ])
  const [chatInput, setChatInput] = useState('')
  const [isChatLoading, setIsChatLoading] = useState(false)

  const maxDataPoints = 30;

  const fetchWorkOrders = async () => {
    try {
      const res = await fetch('http://54.89.167.234:8000/api/work-orders')
      const json = await res.json()
      setWorkOrders(json)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchWorkOrders()

    const ws = new WebSocket('ws://54.89.167.234:8000/ws/sensors')

    ws.onopen = () => {
      console.log('Connected to WebSocket')
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
        setTimeout(fetchWorkOrders, 1500)
      } else if (!reading.is_anomaly && isAnomaly) {
        setIsAnomaly(false)
      }
    }

    ws.onclose = () => {
      console.log('Disconnected from WebSocket')
      setIsConnected(false)
    }

    return () => {
      ws.close()
    }
  }, [isAnomaly])

  const triggerAnomaly = async () => {
    try {
      await fetch('http://54.89.167.234:8000/api/trigger-anomaly', { method: 'POST' })
      // Poll for new work orders after a short delay to allow agent processing
      setTimeout(fetchWorkOrders, 3000)
      setTimeout(fetchWorkOrders, 6000)
    } catch (e) {
      console.error(e)
    }
  }

  const resetAnomaly = async () => {
    try {
      await fetch('http://54.89.167.234:8000/api/reset-anomaly', { method: 'POST' })
      setIsAnomaly(false)
      fetchWorkOrders() // Clear the UI list immediately
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
      const res = await fetch('http://54.89.167.234:8000/api/chat', {
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
      
      {/* Header Section */}
      <header className="app-header">
        <h1 className="app-title">
          <Activity size={28} color="#C8956C" strokeWidth={2.5} />
          MachineWhisperer
        </h1>
        
        <div style={{ padding: '8px 16px', borderRadius: '9999px', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '14px', fontWeight: 500, backgroundColor: isConnected ? '#F2EDE4' : '#FFF0E8', color: isConnected ? '#8B6F5E' : '#9E3E15' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: isConnected ? '#C8956C' : '#D35400', animation: isConnected ? 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' : 'none' }}></div>
          {isConnected ? 'Sensors Online' : 'Sensors Offline'}
        </div>
      </header>

      {/* Main Content Area */}
      <main className="app-main">
        
        {/* Left panel (charts area) */}
        <div className="left-panel custom-scrollbar">

          {/* Status Card */}
          <div style={{ gridColumn: '1 / -1', background: '#FFFFFF', border: '1px solid #E8DDD0', borderLeft: '3px solid #C8956C', borderRadius: '16px', padding: '24px 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
              <div style={{ width: '40px', height: '40px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: isAnomaly ? '#FFF0E8' : '#F2EDE4', color: isAnomaly ? '#D35400' : '#8B6F5E' }}>
                {isAnomaly ? <AlertCircle size={20} strokeWidth={2.5} /> : <CheckCircle2 size={20} strokeWidth={2.5} />}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '26px', fontWeight: 500, color: '#2C2416', margin: '0 0 4px 0' }}>
                  {isAnomaly ? 'Anomaly Detected' : 'All Systems Nominal'}
                </h2>
                <p style={{ color: '#7A6A58', fontSize: '15px', margin: 0 }}>
                  {isAnomaly ? 'Agent is analyzing the fault...' : 'Machine operating within normal parameters.'}
                </p>
              </div>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button 
                  onClick={triggerAnomaly} 
                  className="active:scale-95 active:brightness-90 active:shadow-inner transition-all duration-150 active:ring-4 active:ring-[#C8956C]/50 focus:outline-none"
                  style={{ background: '#C8956C', color: 'white', borderRadius: '8px', padding: '12px 28px', fontWeight: 500, fontSize: '15px', border: 'none', cursor: 'pointer' }}>
                  Simulate Fault
                </button>
                <button 
                  onClick={resetAnomaly} 
                  className="active:scale-95 active:brightness-90 active:shadow-inner transition-all duration-150 active:ring-4 active:ring-[#C8956C]/50 focus:outline-none"
                  style={{ background: 'transparent', border: '1.5px solid #C8956C', color: '#C8956C', borderRadius: '8px', padding: '12px 28px', fontWeight: 500, fontSize: '15px', cursor: 'pointer' }}>
                  Reset Sensors
                </button>
              </div>

              {data.length > 0 && data[data.length - 1].rul_years !== undefined && (
                <div style={{ background: '#FAF8F4', border: '1px solid #E0D5C8', borderRadius: '16px', padding: '20px 32px', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginLeft: '16px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#7A6A58', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>Remaining Useful Life</span>
                  <div style={{ fontSize: '32px', fontWeight: 300, color: '#2C2416', lineHeight: 1.2, display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                    <span style={{ fontWeight: 600 }}>{data[data.length - 1].rul_years ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>yr</span>
                    <span style={{ fontWeight: 600, marginLeft: '4px' }}>{data[data.length - 1].rul_days ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>days</span>
                    <span style={{ fontWeight: 600, marginLeft: '4px' }}>{data[data.length - 1].rul_hrs ?? 0}</span>
                    <span style={{ fontSize: '14px', color: '#7A6A58' }}>hrs</span>
                  </div>
                  {data[data.length - 1].health_pct !== undefined && (
                    <div style={{ marginTop: '8px', width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <span style={{ fontSize: '11px', color: '#7A6A58' }}>Machine Health</span>
                        <span style={{ fontSize: '11px', fontWeight: 600, color: (data[data.length - 1].health_pct ?? 0) > 50 ? '#2D6A4F' : (data[data.length - 1].health_pct ?? 0) > 20 ? '#C9622F' : '#DC2626' }}>{data[data.length - 1].health_pct}%</span>
                      </div>
                      <div style={{ height: '6px', background: '#E8E2D9', borderRadius: '3px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${data[data.length - 1].health_pct ?? 0}%`, background: (data[data.length - 1].health_pct ?? 0) > 50 ? '#2D6A4F' : (data[data.length - 1].health_pct ?? 0) > 20 ? '#C9622F' : '#DC2626', borderRadius: '3px', transition: 'width 1s ease' }}></div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          
          <ChartCard title="Vibration" dataKey="vibration" color="#C8956C" />
          <ChartCard title="Voltage" dataKey="volt" color="#8B6F5E" />
          <ChartCard title="Pressure" dataKey="pressure" color="#A98C78" />
          <ChartCard title="Rotation" dataKey="rotate" color="#D4A373" />

          {/* Work Orders Section */}
          <div className="work-order-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 className="work-order-section-title">
                <ClipboardList size={22} color="#C8956C" />
                Active Maintenance Orders
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
                No active work orders. System is healthy.
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
                    <p className="wo-explanation">{wo.explanation}</p>
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

        {/* Right panel (chat) */}
        <div className="right-panel">
          <div style={{ padding: '20px 16px', borderBottom: '1px solid #E8DDD0', display: 'flex', alignItems: 'center', gap: '12px', background: '#FFFFFF' }}>
            <Bot size={24} color="#C8956C" />
            <h2 style={{ fontFamily: "'Playfair Display', serif", fontSize: '20px', fontWeight: 500, color: '#2C2416', margin: 0 }}>AI Assistant</h2>
          </div>
          
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
                Analyzing system data...
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
        </div>

      </main>
    </div>
  )
}

export default App
