FROM node:24-slim AS deps

WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM node:24-slim AS build

WORKDIR /app
COPY --from=deps /app/node_modules node_modules
COPY web .
RUN npm run build

FROM node:24-slim AS runtime

ENV NODE_ENV=production

WORKDIR /app
COPY --from=build /app/node_modules node_modules
COPY --from=build /app/.next .next
COPY --from=build /app/package.json package.json
COPY --from=build /app/next.config.ts next.config.ts

USER node

EXPOSE 3000
CMD ["npm", "run", "start"]
