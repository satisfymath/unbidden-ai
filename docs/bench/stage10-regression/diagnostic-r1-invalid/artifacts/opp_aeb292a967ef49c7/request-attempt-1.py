{
 "method": "PUT",
 "path": "/api/v1/spool/{value}/measure",
 "query": {},
 "body": {
  "weight": 500
 },
 "values_sql": "BEGIN READ ONLY; SELECT spool.id FROM spool JOIN filament ON filament.id=spool.filament_id ORDER BY spool.id LIMIT 100; COMMIT;",
 "why": "Measuring a spool loads its filament then reads filament by vendor_id to resolve the vendor relation for the response.",
 "table": "filament",
 "column": "vendor_id"
}