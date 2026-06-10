import { NextResponse } from 'next/server';
import { redis } from '@/lib/redis';

export async function GET() {
  try {
    const dataStr = await redis.get('latest_portfolio_status');
    if (!dataStr) {
      // Chiave non presente o scaduta (il bot python potrebbe essere offline)
      return NextResponse.json({ status: 'waiting', message: 'In attesa di dati dal motore Python...' }, { status: 404 });
    }
    
    // Essendo una stringa JSON valida prodotta da Python, la parsiamo
    const data = JSON.parse(dataStr);
    
    return NextResponse.json({ status: 'success', data });
  } catch (error: any) {
    console.error("Errore lettura Redis in /api/portfolio:", error.message);
    return NextResponse.json({ status: 'error', message: 'Impossibile connettersi al database Redis (Railway)' }, { status: 500 });
  }
}
