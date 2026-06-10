"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card, Title, Text, Grid, Metric, Table, TableHead, TableRow, TableHeaderCell, TableBody, TableCell, Badge, Switch, Dialog, DialogPanel } from "@tremor/react";
import { createChart, IChartApi, CandlestickSeriesPartialOptions, ColorType } from "lightweight-charts";

export default function Dashboard() {
  const [sistemaArmato, setSistemaArmato] = useState(false);
  
  // Stati live
  const [portfolio, setPortfolio] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);

  // Modal Genesis
  const [isGenesisModalOpen, setIsGenesisModalOpen] = useState(false);
  const [genesisData, setGenesisData] = useState<any>(null);
  const [genesisLoading, setGenesisLoading] = useState(false);

  const handleRowClick = async (epic: string) => {
    setGenesisData(null);
    setGenesisLoading(true);
    setIsGenesisModalOpen(true);
    try {
      const res = await fetch(`/api/genesis?epic=${epic}`);
      const data = await res.json();
      if (data.status === 'success') {
        setGenesisData(data.genesis);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setGenesisLoading(false);
    }
  };

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const res = await fetch("/api/portfolio");
        if (!res.ok) {
          setIsOffline(true);
          return;
        }
        const data = await res.json();
        if (data.status === 'success' && data.data) {
          setPortfolio(data.data);
          setIsOffline(false);
        } else if (data.status === 'waiting') {
           // Continua a mostrare Loading
        }
      } catch (err) {
        setIsOffline(true);
      } finally {
        setIsLoading(false);
      }
    };
    
    const fetchSystemStatus = async () => {
      try {
        const res = await fetch("/api/system");
        if (res.ok) {
          const data = await res.json();
          setSistemaArmato(data.system_armed);
        }
      } catch (e) { }
    };

    fetchPortfolio();
    fetchSystemStatus();

    const interval = setInterval(fetchPortfolio, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleSistemaArmatoToggle = async (val: boolean) => {
    setSistemaArmato(val);
    try {
      await fetch("/api/system", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_armed: val })
      });
    } catch (e) {
      console.error("Failed to toggle system");
    }
  };

  const handleResetStats = async () => {
    if (confirm("Sei sicuro di voler azzerare le statistiche? Il capitale di base verrà resettato al saldo attuale su Capital.com e il PnL ripartirà da zero.")) {
      try {
        await fetch("/api/reset", { method: "POST" });
        alert("Statistiche azzerate con successo. Attendi qualche secondo per il refresh dei dati.");
      } catch (e) {
        console.error("Failed to reset stats");
      }
    }
  };

  useEffect(() => {
    if (chartContainerRef.current) {
      const chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth,
        height: 400,
        layout: {
          background: { type: ColorType.Solid, color: '#ffffff' },
          textColor: '#333',
        },
        grid: {
          vertLines: { color: '#f0f0f0' },
          horzLines: { color: '#f0f0f0' },
        },
      });

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#f43f5e',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#f43f5e',
      } as CandlestickSeriesPartialOptions);

      candleSeries.setData([
        { time: '2026-06-08', open: 18400, high: 18500, low: 18350, close: 18450 },
        { time: '2026-06-09', open: 18450, high: 18600, low: 18420, close: 18520 },
        { time: '2026-06-10', open: 18520, high: 18550, low: 18200, close: 18250 },
      ]);

      chartRef.current = chart;

      const handleResize = () => {
        chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
      };
      window.addEventListener('resize', handleResize);
      return () => {
        window.removeEventListener('resize', handleResize);
        chart.remove();
      };
    }
  }, []);

  const formatEuro = (val: number) => {
    if (val === undefined || val === null) return "€ 0,00";
    return "€ " + val.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  
  const formatPct = (val: number) => {
    if (val === undefined || val === null) return "0.00%";
    const sign = val > 0 ? "+" : "";
    return sign + val.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
  };

  const initialCap = portfolio?.initial_capital ?? portfolio?.total_capital ?? 0;
  const totalCapital = portfolio?.total_capital ?? initialCap;
  const historicPnlUsd = portfolio?.historic_pnl_usd ?? 0;
  const historicPnlPct = portfolio?.historic_pnl_pct ?? 0;
  
  const dailyBase = portfolio?.daily_starting_capital ?? initialCap;
  const dailyPnlUsd = portfolio?.daily_pnl_usd ?? 0;
  const dailyPnlPct = portfolio?.daily_pnl_pct ?? 0;
  
  const investedCap = portfolio?.invested_capital ?? 0;
  const openPositions = portfolio?.open_positions ?? [];
  const notionalTotal = openPositions.reduce((sum: number, p: any) => sum + (p.notional_usd || 0), 0);

  const renderMetric = (value: string) => {
    if (isLoading) return <Metric className="text-slate-400">Caricamento...</Metric>;
    if (isOffline) return <Metric className="text-rose-500">Offline</Metric>;
    return <Metric className="text-slate-900">{value}</Metric>;
  };

  return (
    <main className="p-8 bg-slate-50 min-h-screen text-slate-900 font-sans flex flex-col">
      <div className="flex-grow">
        <div className="flex justify-between items-center mb-8">
          <Title className="text-3xl font-bold text-slate-900">Alfacore V8 - Terminale Istituzionale</Title>
          <div className="flex items-center gap-4">
            <button
              onClick={handleResetStats}
              className="px-4 py-3 rounded-xl font-bold text-slate-600 bg-white border border-slate-200 shadow-sm hover:bg-slate-50 hover:text-slate-900 transition-colors"
            >
              🔄 Azzera PnL
            </button>
            <button
              onClick={() => handleSistemaArmatoToggle(!sistemaArmato)}
              className={`relative overflow-hidden group px-6 py-3 rounded-xl font-extrabold tracking-wide text-white shadow-xl transition-all duration-300 transform hover:-translate-y-1 active:translate-y-1 ${
                sistemaArmato 
                  ? "bg-gradient-to-r from-emerald-500 to-teal-500 shadow-emerald-500/40 ring-4 ring-emerald-500/30" 
                  : "bg-gradient-to-r from-rose-500 to-red-600 shadow-rose-500/40 ring-4 ring-rose-500/30"
              }`}
            >
              <div className="absolute inset-0 w-full h-full bg-white/20 group-hover:translate-x-full transition-transform duration-700 ease-out -skew-x-12 -translate-x-full"></div>
              <div className="flex items-center gap-3 relative z-10">
                <div className="flex items-center justify-center">
                  <div className={`w-3 h-3 rounded-full ${sistemaArmato ? "bg-white animate-ping absolute" : "hidden"}`}></div>
                  <div className={`w-3 h-3 rounded-full relative z-10 ${sistemaArmato ? "bg-white" : "bg-red-200"}`}></div>
                </div>
                <span>{sistemaArmato ? "SISTEMA ARMATO (LIVE)" : "KILL SWITCH (DRY RUN)"}</span>
              </div>
            </button>
          </div>
        </div>

        <Grid numItemsSm={1} numItemsLg={3} className="gap-6 mb-8">
          <Card decoration="top" decorationColor="blue" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Capitale Iniziale Globale</Text>
            {renderMetric(formatEuro(initialCap))}
            <div className="mt-4">
              <Text className="text-slate-500">Profitti/Perdite Storiche</Text>
              <Text className={historicPnlUsd >= 0 ? "text-emerald-600 font-bold text-lg" : "text-rose-600 font-bold text-lg"}>
                {isLoading ? "..." : isOffline ? "N/A" : `${formatEuro(historicPnlUsd)} (${formatPct(historicPnlPct)})`}
              </Text>
            </div>
          </Card>

          <Card decoration="top" decorationColor="emerald" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Capitale Attuale Capitalizzato</Text>
            {renderMetric(formatEuro(totalCapital))}
            <div className="mt-4">
              <Text className="text-slate-500">Profitti/Perdite Odierne</Text>
              <Text className={dailyPnlUsd >= 0 ? "text-emerald-600 font-bold text-lg" : "text-rose-600 font-bold text-lg"}>
                {isLoading ? "..." : isOffline ? "N/A" : `${formatEuro(dailyPnlUsd)} (${formatPct(dailyPnlPct)})`}
              </Text>
            </div>
          </Card>

          <Card decoration="top" decorationColor="amber" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Margine Impegnato (Investito)</Text>
            {renderMetric(formatEuro(investedCap))}
            <div className="mt-4">
              <Text className="text-slate-500">Esposizione Nominale Complessiva</Text>
              <Text className="text-slate-700 font-bold text-lg">
                {isLoading ? "..." : isOffline ? "N/A" : formatEuro(notionalTotal)}
              </Text>
            </div>
          </Card>
        </Grid>

        <Card className="bg-white border border-slate-200 shadow-sm mb-8">
          <Title className="text-slate-900 mb-4">Main Arena (Grafico Operativo)</Title>
          <div ref={chartContainerRef} className="w-full h-[400px] border border-slate-100 rounded" />
        </Card>

        <Card className="bg-white border border-slate-200 shadow-sm mb-8">
          <Title className="text-slate-900">Posizioni Aperte in Tempo Reale</Title>
          <Table className="mt-5">
            <TableHead>
              <TableRow className="border-b border-slate-200">
                <TableHeaderCell className="text-slate-500 font-medium">Asset</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Direzione</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Margine Investito</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Leva</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Esposizione Nominale</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Size %</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Profitti/Perdite (€)</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">ROE (%)</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {openPositions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-slate-500 py-6">
                    {isLoading ? "Caricamento in corso..." : isOffline ? "Motore Python Disconnesso" : "Nessuna posizione aperta attualmente."}
                  </TableCell>
                </TableRow>
              )}
              {openPositions.map((ordine: any, idx: number) => (
                <TableRow 
                  key={idx} 
                  className="hover:bg-slate-100 transition-colors border-b border-slate-200 cursor-pointer"
                  onClick={() => handleRowClick(ordine.epic)}
                >
                  <TableCell className="font-bold text-slate-900">{ordine.epic}</TableCell>
                  <TableCell>
                    <Badge color={ordine.direction === "BUY" ? "emerald" : "rose"}>
                      {ordine.direction}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-slate-700">{formatEuro(ordine.margin_usd)}</TableCell>
                  <TableCell className="text-slate-700">{ordine.leverage}x</TableCell>
                  <TableCell className="text-slate-700">{formatEuro(ordine.notional_usd)}</TableCell>
                  <TableCell className="text-slate-700">{formatPct(ordine.size)}</TableCell>
                  <TableCell className={ordine.upl >= 0 ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                    {formatEuro(ordine.upl)}
                  </TableCell>
                  <TableCell className={ordine.pnl_pct >= 0 ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                    {formatPct(ordine.pnl_pct)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      <div className="border-t border-slate-200 mt-8 pt-4 pb-2 flex flex-wrap gap-8 text-sm font-medium text-slate-600 items-center justify-center bg-white rounded-lg shadow-sm">
        <span className="flex items-center gap-2"><div className={`w-2 h-2 rounded-full ${isOffline ? 'bg-rose-500' : 'bg-emerald-500'}`}></div> Bridge API: {isOffline ? "Offline" : "Stabile"}</span>
        <span className="flex items-center gap-2"><div className={`w-2 h-2 rounded-full ${isLoading ? 'bg-amber-500' : isOffline ? 'bg-rose-500' : 'bg-emerald-500'}`}></div> Motore Python: {isLoading ? "Attesa..." : isOffline ? "Disconnesso" : "Online"}</span>
      </div>

      <Dialog open={isGenesisModalOpen} onClose={() => setIsGenesisModalOpen(false)}>
        <DialogPanel className="max-w-md">
          <Title className="mb-4">Genesi Operazione</Title>
          {genesisLoading ? (
            <Text>Estrazione memoria in corso...</Text>
          ) : genesisData ? (
            <div className="space-y-4">
              <div>
                <Text className="font-medium">Asset</Text>
                <Text className="font-bold text-lg">{genesisData.epic}</Text>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Text className="font-medium">Direzione</Text>
                  <Badge color={genesisData.direction === "BUY" ? "emerald" : "rose"}>
                    {genesisData.direction}
                  </Badge>
                </div>
                <div>
                  <Text className="font-medium">Voto Medio (Consiglio)</Text>
                  <Text className="font-bold">{(genesisData.votes_mean * 100).toFixed(0)}%</Text>
                </div>
              </div>
              <div>
                <Text className="font-medium">Motivazione Originale</Text>
                <Text className="mt-1 bg-slate-50 p-3 rounded-lg border border-slate-200 text-sm">
                  Questa posizione è stata approvata dal Supervisor Engine grazie ai segnali combinati dai motori IA, con approvazione matematica assoluta da: <strong className="text-slate-800">{genesisData.source || 'Titano V8'}</strong>
                </Text>
              </div>
              <button 
                className="w-full mt-4 bg-slate-900 text-white rounded-lg py-2 font-medium hover:bg-slate-800 transition-colors"
                onClick={() => setIsGenesisModalOpen(false)}
              >
                Chiudi
              </button>
            </div>
          ) : (
            <Text className="text-rose-500">Dati della Genesi non disponibili. Il trade potrebbe essere troppo vecchio o generato manualmente.</Text>
          )}
        </DialogPanel>
      </Dialog>
    </main>
  );
}
