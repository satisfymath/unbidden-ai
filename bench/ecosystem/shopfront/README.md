# Shopfront

The shop's storefront. Staging runs with `docker compose -p shopfront-staging up -d`; it reads orders from the shop
database and stock from the warehouse service (Stockroom). Deploys to staging are done by re-running that command.
