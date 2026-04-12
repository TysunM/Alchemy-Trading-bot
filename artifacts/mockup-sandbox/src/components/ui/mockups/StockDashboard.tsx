import React, { useState } from 'react';
// Assuming you have lucide-react installed for icons. If not, you can install it or replace these with standard SVGs.
import { 
  LineChart, Activity, DollarSign, ArrowUpRight, ArrowDownRight, 
  Maximize2, Clock, Settings, Search, Bell, User, ArrowLeft, 
  PenTool, BarChart2, Layers, BookOpen
} from 'lucide-react';

// --- Types ---
type ViewState = 'dashboard' | 'advanced-chart';

// --- Mock Data ---
const MOCK_POSITIONS = [
  { symbol: 'AAPL', price: 173.50, change: '+1.2%', isPositive: true, shares: 50 },
  { symbol: 'TSLA', price: 188.20, change: '-2.4%', isPositive: false, shares: 20 },
  { symbol: 'NVDA', price: 902.10, change: '+4.5%', isPositive: true, shares: 15 },
];

export default function StockDashboard() {
  const [currentView, setCurrentView] = useState<ViewState>('dashboard');

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-sans flex flex-col">
      {/* Top Navigation Bar */}
      <header className="h-16 border-b border-gray-800 flex items-center justify-between px-6 bg-gray-900/50 backdrop-blur-md">
        <div className="flex items-center gap-2 text-xl font-bold text-blue-500">
          <Activity className="w-6 h-6" />
          <span>AlchemyTrade</span>
        </div>
        
        <div className="flex items-center bg-gray-800 rounded-lg px-3 py-1.5 w-64 border border-gray-700">
          <Search className="w-4 h-4 text-gray-400 mr-2" />
          <input 
            type="text" 
            placeholder="Search markets, news..." 
            className="bg-transparent border-none outline-none text-sm w-full placeholder-gray-500"
          />
        </div>

        <div className="flex items-center gap-4">
          <button className="text-gray-400 hover:text-white transition-colors relative">
            <Bell className="w-5 h-5" />
            <span className="absolute -top-1 -right-1 w-2 h-2 bg-blue-500 rounded-full"></span>
          </button>
          <button className="text-gray-400 hover:text-white transition-colors">
            <Settings className="w-5 h-5" />
          </button>
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-purple-500 flex items-center justify-center cursor-pointer">
            <User className="w-4 h-4 text-white" />
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden flex flex-col relative">
        {currentView === 'dashboard' ? (
          <DashboardView onOpenChart={() => setCurrentView('advanced-chart')} />
        ) : (
          <AdvancedChartView onClose={() => setCurrentView('dashboard')} />
        )}
      </main>
    </div>
  );
}

// --- Sub-components ---

function DashboardView({ onOpenChart }: { onOpenChart: () => void }) {
  return (
    <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 lg:flex-row">
      {/* Left Column - Stats & Simplified Chart */}
      <div className="flex-1 flex flex-col gap-6">
        
        {/* Key Metrics row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard title="Portfolio Value" value="$124,562.00" change="+2.4%" isPositive={true} icon={<DollarSign className="w-5 h-5" />} />
          <StatCard title="Today's P&L" value="+$2,934.50" change="+1.1%" isPositive={true} icon={<Activity className="w-5 h-5" />} />
          <StatCard title="Buying Power" value="$45,000.00" change="" isPositive={true} icon={<LineChart className="w-5 h-5" />} />
        </div>

        {/* Simplified Chart Widget */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-4 shadow-lg h-[400px]">
          <div className="flex justify-between items-center">
            <div>
              <h2 className="text-lg font-semibold text-gray-200">Market Overview</h2>
              <p className="text-sm text-gray-500">S&P 500 • Simplified View</p>
            </div>
            {/* The important transition button */}
            <button 
              onClick={onOpenChart}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-md shadow-blue-900/20"
            >
              <Maximize2 className="w-4 h-4" />
              Full Pro Chart
            </button>
          </div>
          
          {/* Conceptual simple chart visualization */}
          <div className="flex-1 border border-gray-800 rounded-lg bg-gray-950/50 flex items-center justify-center relative overflow-hidden group">
            {/* This is a placeholder for a simple AreaChart (e.g. Recharts) */}
            <div className="absolute inset-0 bg-gradient-to-t from-blue-900/20 to-transparent"></div>
            <svg viewBox="0 0 100 50" className="w-full h-full opacity-60 text-blue-500 stroke-current drop-shadow-md preserve-3d">
              <path fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" d="M0,40 Q10,35 20,40 T40,20 T60,30 T80,10 T100,15" />
            </svg>
            <p className="absolute text-gray-500 text-sm font-medium">Simplified Uncongested Chart</p>
          </div>
        </div>
      </div>

      {/* Right Column - Side Panel (Positions & Quick Actions) */}
      <div className="w-full lg:w-80 flex flex-col gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg flex-1">
          <h2 className="text-lg font-semibold text-gray-200 mb-4">Your Positions</h2>
          <div className="flex flex-col gap-3">
            {MOCK_POSITIONS.map((pos) => (
              <div key={pos.symbol} className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50 border border-gray-700/50 hover:bg-gray-800 transition-colors cursor-pointer">
                <div>
                  <h3 className="font-bold text-gray-200">{pos.symbol}</h3>
                  <p className="text-xs text-gray-500">{pos.shares} Shares</p>
                </div>
                <div className="text-right">
                  <p className="font-semibold text-gray-200">${pos.price.toFixed(2)}</p>
                  <p className={`text-xs flex items-center justify-end ${pos.isPositive ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.isPositive ? <ArrowUpRight className="w-3 h-3 mr-1" /> : <ArrowDownRight className="w-3 h-3 mr-1" />}
                    {pos.change}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AdvancedChartView({ onClose }: { onClose: () => void }) {
  // Mock timeframes
  const timeframes = ['1m', '5m', '15m', '1H', '4H', '1D', '1W', '1M'];
  
  return (
    <div className="flex-1 flex flex-col bg-[#131722]"> {/* TradingView typical dark background */}
      
      {/* Advanced Chart Top Toolbar */}
      <div className="h-12 border-b border-gray-800 flex items-center justify-between px-4 bg-[#1e222d]">
        <div className="flex items-center gap-4">
          <button onClick={onClose} className="flex items-center text-gray-400 hover:text-white transition-colors mr-2">
            <ArrowLeft className="w-5 h-5 mr-1" /> Back
          </button>
          
          <div className="flex items-center gap-2 border-r border-gray-700 pr-4">
            <span className="font-bold text-lg text-gray-100">BTC/USD</span>
            <span className="text-green-400 text-sm font-medium">+2.45%</span>
          </div>

          {/* Timeframe Selector */}
          <div className="flex gap-1">
            {timeframes.map(tf => (
              <button key={tf} className="px-2 py-1 text-xs font-medium rounded text-gray-400 hover:bg-gray-700 hover:text-gray-100 transition-colors focus:bg-blue-600 focus:text-white">
                {tf}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-100">
            <Activity className="w-4 h-4" /> Indicators
          </button>
          <button className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-100">
            <Clock className="w-4 h-4" /> Alerts
          </button>
        </div>
      </div>

      <div className="flex-1 flex">
        {/* Left Drawing Tools Sidebar */}
        <div className="w-12 border-r border-gray-800 bg-[#1e222d] flex flex-col items-center py-4 gap-4 text-gray-400">
          <button className="hover:text-white p-2 rounded hover:bg-gray-700"><PenTool className="w-5 h-5" /></button>
          <button className="hover:text-white p-2 rounded hover:bg-gray-700"><BarChart2 className="w-5 h-5" /></button>
          <button className="hover:text-white p-2 rounded hover:bg-gray-700"><Layers className="w-5 h-5" /></button>
        </div>

        {/* Main Chart Area */}
        <div className="flex-1 relative flex items-center justify-center border-r border-gray-800">
           {/* In a real app, you would mount an Advanced Charting library here (e.g., TradingView Lightweight Charts) */}
           <div className="text-center text-gray-500">
             <LineChart className="w-24 h-24 mx-auto mb-4 opacity-20" />
             <h2 className="text-2xl font-bold opacity-40">TradingView Chart Integration Area</h2>
             <p className="mt-2 text-sm opacity-60 max-w-md mx-auto">
               This space is dedicated to the full charting library. It scales beautifully, reacts to the timeframes above, and utilizes the drawing tools on the left.
             </p>
           </div>
        </div>

        {/* Right Action/News Sidebar */}
        <div className="w-80 bg-[#1e222d] flex flex-col">
          {/* Order Entry */}
          <div className="p-4 border-b border-gray-800 flex-1">
            <h3 className="font-semibold text-gray-200 mb-4">Order Entry</h3>
            
            <div className="flex bg-gray-800 rounded-lg p-1 mb-4">
              <button className="flex-1 py-1.5 text-sm font-medium rounded bg-gray-700 text-white">Market</button>
              <button className="flex-1 py-1.5 text-sm font-medium rounded text-gray-400 hover:text-gray-200">Limit</button>
              <button className="flex-1 py-1.5 text-sm font-medium rounded text-gray-400 hover:text-gray-200">Stop</button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Size</label>
                <input type="number" className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm text-gray-200 outline-none focus:border-blue-500" placeholder="0.00" />
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-xs text-gray-500 mb-1 block">Take Profit</label>
                  <input type="number" className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm text-gray-200 outline-none focus:border-green-500" placeholder="0.00" />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-gray-500 mb-1 block">Stop Loss</label>
                  <input type="number" className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm text-gray-200 outline-none focus:border-red-500" placeholder="0.00" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-6">
                <button className="bg-green-600 hover:bg-green-500 text-white font-bold py-3 rounded-lg shadow-lg">BUY</button>
                <button className="bg-red-600 hover:bg-red-500 text-white font-bold py-3 rounded-lg shadow-lg">SELL</button>
              </div>
            </div>
          </div>

          {/* Live News Feed */}
          <div className="p-4 flex-1 overflow-y-auto">
             <div className="flex items-center gap-2 mb-4 text-gray-200">
               <BookOpen className="w-4 h-4" />
               <h3 className="font-semibold">Live News Cycle</h3>
             </div>
             
             <div className="space-y-4">
                <NewsItem time="10:42 AM" title="Federal Reserve signals potential rate holds for Q3." />
                <NewsItem time="09:15 AM" title="Tech sector shows strong resilience amidst global market sell-off." />
                <NewsItem time="08:30 AM" title="Unemployment claims drop slightly below expected margins." />
             </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Minor helper components ---

function StatCard({ title, value, change, isPositive, icon }: any) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg flex flex-col justify-between hover:border-gray-700 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-500">{title}</span>
        <div className="text-gray-400 bg-gray-800/50 p-2 rounded-lg">{icon}</div>
      </div>
      <div className="flex items-end justify-between">
        <h3 className="text-2xl font-bold text-gray-100">{value}</h3>
        {change && (
          <span className={`text-sm font-medium flex items-center ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? <ArrowUpRight className="w-4 h-4 mr-1" /> : <ArrowDownRight className="w-4 h-4 mr-1" />}
            {change}
          </span>
        )}
      </div>
    </div>
  );
}

function NewsItem({ time, title }: { time: string, title: string }) {
  return (
    <div className="border-l-2 border-blue-500 pl-3">
      <span className="text-xs text-blue-400 font-mono mb-1 block">{time}</span>
      <p className="text-sm text-gray-300 leading-snug">{title}</p>
    </div>
  );
}
