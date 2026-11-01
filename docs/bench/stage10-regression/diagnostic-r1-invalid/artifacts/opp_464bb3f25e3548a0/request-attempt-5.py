{
 "method": "DELETE",
 "path": "/api/v1/vendor/{value}",
 "query": {},
 "body": null,
 "values_sql": "BEGIN READ ONLY; SELECT vendor.id FROM vendor JOIN filament ON filament.vendor_id = vendor.id JOIN spool ON spool.filament_id = filament.id GROUP BY vendor.id ORDER BY vendor.id; COMMIT;",
 "why": "Deleting a vendor must clear the vendor of its filaments and therefore loads the spools of each affected filament by spool.filament_id.",
 "table": "spool",
 "column": "filament_id"
}