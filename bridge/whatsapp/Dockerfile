FROM node:20-slim

# System dependencies for Baileys (canvas / sharp native modules)
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY index.js ./

# Session data persisted as a volume mount
VOLUME ["/app/wa_session"]

ENV NODE_ENV=production
ENV SARAS_URL=http://saras:8001
ENV BRIDGE_PORT=3001
ENV SESSION_DIR=/app/wa_session

EXPOSE 3001

CMD ["node", "index.js"]
