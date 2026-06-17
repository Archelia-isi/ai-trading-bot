export const dynamic = 'force-dynamic';

import { NextResponse } from 'next/server';
import { redis } from '@/lib/redis';

export async function POST() {
  try {
    // Cancellando queste due chiavi, l'Audit Engine al prossimo ciclo
    // ripartirà dal capitale attuale (new_equity) come fosse il giorno 0.
    await redis.del('bot_initial_capital', 'daily_starting_capital');
    return NextResponse.json({ status: 'success', message: 'Statistiche azzerate con successo' });
  } catch (error: any) {
    console.error("Errore reset statistiche:", error.message);
    return NextResponse.json({ status: 'error', message: 'Errore DB' }, { status: 500 });
  }
}
