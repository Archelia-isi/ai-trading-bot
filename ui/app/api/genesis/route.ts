import { NextResponse } from 'next/server';
import { redis } from '@/lib/redis';

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const epic = searchParams.get('epic');
    
    if (!epic) {
      return NextResponse.json({ status: 'error', message: 'Epic is required' }, { status: 400 });
    }

    const genesisRaw = await redis.hget('trade_genesis', epic);
    if (!genesisRaw) {
      return NextResponse.json({ status: 'error', message: 'Genesis non trovata per questo asset' }, { status: 404 });
    }

    const genesis = JSON.parse(genesisRaw);
    return NextResponse.json({ status: 'success', genesis });
  } catch (error: any) {
    console.error("Errore fetch genesis:", error.message);
    return NextResponse.json({ status: 'error', message: 'Errore DB' }, { status: 500 });
  }
}
