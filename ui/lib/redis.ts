import Redis from 'ioredis';

// Singleton instance per evitare connessioni multiple in sviluppo (Hot Reloading in Next.js)
const globalForRedis = global as unknown as { redis: Redis };

export const redis =
  globalForRedis.redis ||
  new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

if (process.env.NODE_ENV !== 'production') globalForRedis.redis = redis;
