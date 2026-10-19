FROM node:18-alpine

WORKDIR /app

# The frontend currently is a simple static HTML/JS/CSS served directly, but for an enterprise upgrade
# we will serve it using a lightweight web server (like nginx) or node static server.
# Let's install a simple static server for now.
RUN npm install -g serve

COPY . .

# Expose port 3000
EXPOSE 3000

# Start server
CMD ["serve", "-s", ".", "-l", "3000"]
