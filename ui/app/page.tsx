"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card, Title, Text, Grid, Metric, Table, TableHead, TableRow, TableHeaderCell, TableBody, TableCell, Badge, Dialog, DialogPanel, Switch } from "@tremor/react";
import { createChart, IChartApi, CandlestickSeriesPartialOptions } from "lightweight-charts";

// Mock dati JSON
const ordiniMock = [
  { id: 1, asset: "US100", direzione: "Lungo", capitale: 1500, leva: 20, esposizione: 30000, prezzoIn: 18500.5, prezzoAtt: 18520.0, pnl: 295.5, roe: 19.7, prob: 0.85, sent: 0.65, lat: "12ms", news: "La Fed mantiene i tassi stabili per il trimestre corrente." },
  { id: 2, asset: "BTC/USDT", direzione: "Corto", capitale: 500, leva: 10, esposizione: 5000, prezzoIn: 68000, prezzoAtt: 67500, pnl: 36.7, roe: 7.34, prob: 0.72, sent: -0.4, lat: "8ms", news: "Imminente stretta normativa asiatica sulle criptovalute." }
];

export default function Dashboard() {
  const [isOpen, setIsOpen] = useState(false);
  const [ordineSelezionato, setOrdineSelezionato] = useState<any>(null);
  const [sistemaArmato, setSistemaArmato] = useState(false);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (chartContainerRef.current) {
      const chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth,
        height: 400,
        layout: {
          background: { type: 'solid', color: '#ffffff' },
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

      // Dati mock per il grafico
      candleSeries.setData([
        { time: '2026-06-08', open: 18400, high: 18500, low: 18350, close: 18450 },
        { time: '2026-06-09', open: 18450, high: 18600, low: 18420, close: 18520 },
        { time: '2026-06-10', open: 18520, high: 18550, low: 18200, close: 18250 },
      ]);

      // Markers (Segnali Operativi)
      candleSeries.setMarkers([
        { time: '2026-06-09', position: 'belowBar', color: '#10b981', shape: 'arrowUp', text: 'Compra' },
        { time: '2026-06-10', position: 'aboveBar', color: '#f43f5e', shape: 'arrowDown', text: 'Vendi' }
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

  const apriDettagli = (ordine: any) => {
    setOrdineSelezionato(ordine);
    setIsOpen(true);
  };

  return (
    <main className="p-8 bg-slate-50 min-h-screen text-slate-900 font-sans flex flex-col">
      <div className="flex-grow">
        {/* Top Bar - Titolo e Interruttore */}
        <div className="flex justify-between items-center mb-8">
          <Title className="text-3xl font-bold text-slate-900">Alfacore V8 - Terminale Istituzionale</Title>
          <div className="flex items-center gap-3 bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
            <Text className="font-medium text-slate-600">Interruttore Generale</Text>
            <Switch checked={sistemaArmato} onChange={setSistemaArmato} color="emerald" />
            <Badge color={sistemaArmato ? "emerald" : "rose"} className="text-sm font-bold">
              {sistemaArmato ? "SISTEMA ARMATO" : "SISTEMA DISARMATO"}
            </Badge>
          </div>
        </div>

        {/* Metriche Contabili */}
        <Grid numItemsSm={1} numItemsLg={3} className="gap-6 mb-8">
          <Card decoration="top" decorationColor="blue" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Capitale Iniziale Globale</Text>
            <Metric className="text-slate-900">€ 50.000,00</Metric>
            <div className="mt-4">
              <Text className="text-slate-500">Profitti/Perdite Latenti (Totale)</Text>
              <Text className="text-emerald-600 font-bold text-lg">+ € 4.250,00 (+8.5%)</Text>
            </div>
          </Card>

          <Card decoration="top" decorationColor="emerald" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Capitale Capitalizzato Odierno</Text>
            <Metric className="text-slate-900">€ 53.800,00</Metric>
            <div className="mt-4">
              <Text className="text-slate-500">Profitti/Perdite Latenti (Oggi)</Text>
              <Text className="text-emerald-600 font-bold text-lg">+ € 450,00 (+0.83%)</Text>
            </div>
          </Card>

          <Card decoration="top" decorationColor="amber" className="bg-white border border-slate-200 shadow-sm">
            <Text className="text-slate-500 font-medium">Capitale Esposto (Margine)</Text>
            <Metric className="text-slate-900">€ 2.000,00</Metric>
            <div className="mt-4">
              <Text className="text-slate-500">Esposizione Nominale Totale</Text>
              <Text className="text-slate-700 font-bold text-lg">€ 35.000,00</Text>
            </div>
          </Card>
        </Grid>

        {/* Grafico Principale (Main Arena) */}
        <Card className="bg-white border border-slate-200 shadow-sm mb-8">
          <Title className="text-slate-900 mb-4">Main Arena (US100 - Segnali Operativi)</Title>
          <div ref={chartContainerRef} className="w-full h-[400px] border border-slate-100 rounded" />
        </Card>

        {/* Registro Operazioni (Ledger) */}
        <Card className="bg-white border border-slate-200 shadow-sm mb-8">
          <Title className="text-slate-900">Registro Operazioni (Ledger)</Title>
          <Table className="mt-5">
            <TableHead>
              <TableRow className="border-b border-slate-200">
                <TableHeaderCell className="text-slate-500 font-medium">Asset</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Direzione</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Capitale Investito</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Leva Finanziaria</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Esposizione Nominale</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Prezzo Ingresso</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Prezzo Attuale</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">Profitti/Perdite (€)</TableHeaderCell>
                <TableHeaderCell className="text-slate-500 font-medium">ROE (%)</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ordiniMock.map((ordine) => (
                <TableRow 
                  key={ordine.id} 
                  className="hover:bg-slate-50 cursor-pointer transition-colors border-b border-slate-100"
                  onClick={() => apriDettagli(ordine)}
                >
                  <TableCell className="font-bold text-slate-900">{ordine.asset}</TableCell>
                  <TableCell>
                    <Badge color={ordine.direzione === "Lungo" ? "emerald" : "rose"}>
                      {ordine.direzione}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-slate-700">€ {ordine.capitale}</TableCell>
                  <TableCell className="text-slate-700">{ordine.leva}x</TableCell>
                  <TableCell className="text-slate-700">€ {ordine.esposizione}</TableCell>
                  <TableCell className="text-slate-700">{ordine.prezzoIn}</TableCell>
                  <TableCell className="text-slate-700">{ordine.prezzoAtt}</TableCell>
                  <TableCell className={ordine.pnl >= 0 ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                    {ordine.pnl >= 0 ? "+" : ""}€ {ordine.pnl}
                  </TableCell>
                  <TableCell className={ordine.roe >= 0 ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                    {ordine.roe >= 0 ? "+" : ""}{ordine.roe}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        {/* Scatola Nera (Pop-up) */}
        <Dialog open={isOpen} onClose={(val) => setIsOpen(val)} static={true}>
          <DialogPanel className="bg-white p-6 rounded-lg border border-slate-200 shadow-xl max-w-2xl">
            <Title className="text-xl font-bold text-slate-900 mb-4 border-b pb-2">Analisi Quantitativa (La Scatola Nera)</Title>
            {ordineSelezionato && (
              <div className="space-y-4">
                <Grid numItems={2} className="gap-4">
                  <div className="bg-slate-50 p-4 rounded border border-slate-100">
                    <Text className="text-slate-500 text-sm">Probabilità XGBoost</Text>
                    <Text className="text-slate-900 font-bold text-lg">{(ordineSelezionato.prob * 100).toFixed(1)}%</Text>
                  </div>
                  <div className="bg-slate-50 p-4 rounded border border-slate-100">
                    <Text className="text-slate-500 text-sm">Sentiment (NLP)</Text>
                    <Text className="text-slate-900 font-bold text-lg">{ordineSelezionato.sent > 0 ? "+" : ""}{ordineSelezionato.sent.toFixed(2)}</Text>
                  </div>
                </Grid>
                <div className="bg-blue-50 p-4 rounded border border-blue-100 mt-4">
                  <Text className="text-blue-800 text-sm font-semibold mb-1">Notizia Finanziaria</Text>
                  <Text className="text-slate-800 italic">"{ordineSelezionato.news}"</Text>
                </div>
              </div>
            )}
            <div className="mt-6 flex justify-end">
              <button 
                className="bg-slate-900 text-white px-5 py-2 rounded font-medium hover:bg-slate-800 transition shadow-sm"
                onClick={() => setIsOpen(false)}
              >
                Chiudi Telemetria
              </button>
            </div>
          </DialogPanel>
        </Dialog>
      </div>

      {/* Telemetria di Sistema (Footer) */}
      <div className="border-t border-slate-200 mt-8 pt-4 pb-2 flex flex-wrap gap-8 text-sm font-medium text-slate-600 items-center justify-center bg-white rounded-lg shadow-sm">
        <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Latenza Database Redis: 0.8ms</span>
        <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Stato Motore NLP: Online</span>
        <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Stato Motore XGBoost: Sincronizzato al mercato</span>
        <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-blue-500"></div> Tempo Esecuzione Algoritmo: 12ms</span>
      </div>
    </main>
  );
}
