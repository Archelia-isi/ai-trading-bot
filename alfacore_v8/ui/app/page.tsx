"use client";

import React, { useState } from "react";
import { Card, Title, Text, Grid, Metric, Table, TableHead, TableRow, TableHeaderCell, TableBody, TableCell, Badge, Dialog, DialogPanel } from "@tremor/react";

// Mock dati JSON da Neon DB per l'interfaccia
const ordiniMock = [
  { id: 1, asset: "US100", direzione: "Lungo", capitale: 1500, leva: 20, esposizione: 30000, prezzoIn: 18500.5, prezzoAtt: 18520.0, pnl: 295.5, roe: 19.7, prob: 0.85, sent: 0.65, lat: "12ms", news: "La Fed mantiene i tassi stabili." },
  { id: 2, asset: "BTC/USDT", direzione: "Corto", capitale: 500, leva: 10, esposizione: 5000, prezzoIn: 68000, prezzoAtt: 67500, pnl: 36.7, roe: 7.34, prob: 0.72, sent: -0.4, lat: "8ms", news: "Nuova regolamentazione in arrivo per le crypto." }
];

export default function Dashboard() {
  const [isOpen, setIsOpen] = useState(false);
  const [ordineSelezionato, setOrdineSelezionato] = useState<any>(null);

  const apriDettagli = (ordine: any) => {
    setOrdineSelezionato(ordine);
    setIsOpen(true);
  };

  return (
    <main className="p-10 bg-white min-h-screen text-slate-900 font-sans">
      <Title className="text-3xl font-bold mb-6 text-slate-900">Alfacore V8 - Terminale Istituzionale</Title>

      {/* Top Bar - Metriche Contabili */}
      <Grid numItemsSm={1} numItemsLg={3} className="gap-6 mb-10">
        <Card decoration="top" decorationColor="blue" className="bg-slate-50 border border-slate-200">
          <Text className="text-slate-500">Capitale Iniziale Globale</Text>
          <Metric className="text-slate-900">€ 50,000.00</Metric>
          <div className="mt-4">
            <Text className="text-slate-500">Profitti/Perdite Latenti (Totale)</Text>
            <Text className="text-emerald-600 font-bold text-lg">+ € 4,250.00 (+8.5%)</Text>
          </div>
        </Card>

        <Card decoration="top" decorationColor="emerald" className="bg-slate-50 border border-slate-200">
          <Text className="text-slate-500">Capitale Capitalizzato Odierno</Text>
          <Metric className="text-slate-900">€ 53,800.00</Metric>
          <div className="mt-4">
            <Text className="text-slate-500">Profitti/Perdite Latenti (Oggi)</Text>
            <Text className="text-emerald-600 font-bold text-lg">+ € 450.00 (+0.83%)</Text>
          </div>
        </Card>

        <Card decoration="top" decorationColor="amber" className="bg-slate-50 border border-slate-200">
          <Text className="text-slate-500">Capitale Esposto (Margine)</Text>
          <Metric className="text-slate-900">€ 2,000.00</Metric>
          <div className="mt-4">
            <Text className="text-slate-500">Esposizione Nominale Totale</Text>
            <Text className="text-slate-700 font-bold text-lg">€ 35,000.00</Text>
          </div>
        </Card>
      </Grid>

      {/* Ledger Ordini */}
      <Card className="bg-white border border-slate-200 shadow-sm">
        <Title className="text-slate-900">Ledger Operazioni Attive</Title>
        <Table className="mt-5">
          <TableHead>
            <TableRow className="border-b border-slate-200">
              <TableHeaderCell className="text-slate-500">Asset</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Direzione</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Capitale Investito</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Leva Finanziaria</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Esposizione Nominale</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Prezzo Ingresso</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Prezzo Attuale</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">Profitti/Perdite (€)</TableHeaderCell>
              <TableHeaderCell className="text-slate-500">ROE (%)</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {ordiniMock.map((ordine) => (
              <TableRow 
                key={ordine.id} 
                className="hover:bg-slate-50 cursor-pointer transition-colors border-b border-slate-100"
                onClick={() => apriDettagli(ordine)}
              >
                <TableCell className="font-medium text-slate-900">{ordine.asset}</TableCell>
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

      {/* La Scatola Nera (Pop-up Interattivo) */}
      <Dialog open={isOpen} onClose={(val) => setIsOpen(val)} static={true}>
        <DialogPanel className="bg-white p-6 rounded-lg border border-slate-200 shadow-xl max-w-2xl">
          <Title className="text-xl text-slate-900 mb-4 border-b pb-2">Analisi Quantitativa (La Scatola Nera)</Title>
          {ordineSelezionato && (
            <div className="space-y-4">
              <Grid numItems={2} className="gap-4">
                <div className="bg-slate-50 p-4 rounded border border-slate-100">
                  <Text className="text-slate-500 text-sm">Probabilità Decidionale (XGBoost)</Text>
                  <Text className="text-slate-900 font-bold text-lg">{(ordineSelezionato.prob * 100).toFixed(1)}%</Text>
                </div>
                <div className="bg-slate-50 p-4 rounded border border-slate-100">
                  <Text className="text-slate-500 text-sm">Punteggio Sentiment (NLP)</Text>
                  <Text className="text-slate-900 font-bold text-lg">{ordineSelezionato.sent > 0 ? "+" : ""}{ordineSelezionato.sent.toFixed(2)}</Text>
                </div>
              </Grid>
              <div className="bg-slate-50 p-4 rounded border border-slate-100">
                <Text className="text-slate-500 text-sm">Latenza di Esecuzione</Text>
                <Text className="text-slate-900 font-bold text-lg">{ordineSelezionato.lat}</Text>
              </div>
              <div className="bg-blue-50 p-4 rounded border border-blue-100 mt-4">
                <Text className="text-blue-800 text-sm font-semibold mb-1">Catalizzatore Notizia (Tradotta)</Text>
                <Text className="text-slate-800 italic">"{ordineSelezionato.news}"</Text>
              </div>
            </div>
          )}
          <div className="mt-6 flex justify-end">
            <button 
              className="bg-slate-900 text-white px-4 py-2 rounded hover:bg-slate-800 transition"
              onClick={() => setIsOpen(false)}
            >
              Chiudi Scatola Nera
            </button>
          </div>
        </DialogPanel>
      </Dialog>
    </main>
  );
}
