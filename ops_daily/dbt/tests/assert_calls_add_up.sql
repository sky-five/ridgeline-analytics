-- Every offered call is answered or abandoned, and no more calls are answered within 60 seconds than answered.
select * from {{ ref('stg_ops__calls') }}
where answered + abandoned != offered or answered_within_60s > answered
