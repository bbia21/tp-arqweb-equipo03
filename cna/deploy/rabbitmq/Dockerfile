# RabbitMQ con el plugin de métricas Prometheus activado dentro de la imagen
# (así no depende de archivos montados desde el host y se puede desplegar en otro nodo)
FROM rabbitmq:4.1-management-alpine
RUN rabbitmq-plugins enable --offline rabbitmq_prometheus
