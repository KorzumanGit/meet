FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

ENV PORT=3847
EXPOSE 3847

CMD ["node", "dist/index.js"]
