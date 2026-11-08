// Logs en JSON a stdout con timestamp, level, service, request_id y message (requisito B2).
const pino = require('pino');

const logger = pino({
  base: { service: process.env.SERVICE_NAME || 'event-bridge' },
  messageKey: 'message',
  timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
  formatters: {
    level: (label) => ({ level: label }),
  },
});

module.exports = logger;
