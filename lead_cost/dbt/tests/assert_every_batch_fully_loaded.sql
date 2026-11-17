-- Bronze: every delivered file landed with the row count its manifest declared (a short file fails here).
select batch_id, source, file, declared_rows, loaded_rows
from {{ source('bronze', 'load_audit') }}
where loaded_rows != declared_rows
