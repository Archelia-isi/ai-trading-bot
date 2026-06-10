import { NextResponse } from 'next/server';
import { redis } from '@/lib/redis';

export async function GET() {
  try {
    const isArmedStr = await redis.get('system_armed');
    const isArmed = isArmedStr === 'true';
    return NextResponse.json({ status: 'success', system_armed: isArmed });
  } catch (error: any) {
    console.error("Errore lettura system_armed:", error.message);
    return NextResponse.json({ status: 'error', message: 'Errore DB' }, { status: 500 });
  }
}

export async function POST(req: Request) {
  try {
    const { system_armed } = await req.json();
    await redis.set('system_armed', system_armed ? 'true' : 'false');
    return NextResponse.json({ status: 'success', system_armed: Boolean(system_armed) });
  } catch (error: any) {
    console.error("Errore scrittura system_armed:", error.message);
    return NextResponse.json({ status: 'error', message: 'Errore DB' }, { status: 500 });
  }
}
