FROM node:20

# Set environment variables
ENV NODE_ENV=development

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Clean install with platform-specific binaries
RUN npm ci --include=dev

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
