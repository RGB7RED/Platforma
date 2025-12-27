FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html
COPY app.js /usr/share/nginx/html/app.js
COPY config.js /usr/share/nginx/html/config.js
COPY styles.css /usr/share/nginx/html/styles.css
COPY assets /usr/share/nginx/html/assets
COPY lib /usr/share/nginx/html/lib

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
