-- Ridgeline: one-time Snowflake setup. Run as ACCOUNTADMIN in a Snowsight worksheet ("Run all").
-- Creates least-privilege roles, an XS warehouse with a credit cap, the databases, and a key-pair
-- service user for dlt + dbt (no password). Replace <PUBLIC_KEY> with the key body (setup.local.sql has it filled in).
use role accountadmin;

-- spend guardrail: suspend everything at 50 credits a month
create resource monitor if not exists ridgeline_monitor
    with credit_quota = 50 frequency = monthly start_timestamp = immediately
    triggers on 80 percent do notify on 100 percent do suspend;

create warehouse if not exists ridgeline_wh
    warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true
    resource_monitor = ridgeline_monitor;

create database if not exists ridgeline_raw;
create database if not exists ridgeline_analytics;

-- roles: loader writes raw, transformer builds analytics, reporter reads marts
create role if not exists ridgeline_loader;
create role if not exists ridgeline_transformer;
create role if not exists ridgeline_reporter;
grant role ridgeline_loader to role sysadmin;
grant role ridgeline_transformer to role sysadmin;
grant role ridgeline_reporter to role sysadmin;

grant usage on warehouse ridgeline_wh to role ridgeline_loader;
grant usage on warehouse ridgeline_wh to role ridgeline_transformer;
grant usage on warehouse ridgeline_wh to role ridgeline_reporter;

grant all on database ridgeline_raw to role ridgeline_loader;
grant usage on database ridgeline_raw to role ridgeline_transformer;
grant usage on future schemas in database ridgeline_raw to role ridgeline_transformer;
grant select on future tables in database ridgeline_raw to role ridgeline_transformer;
grant all on database ridgeline_analytics to role ridgeline_transformer;
grant usage on database ridgeline_analytics to role ridgeline_reporter;
grant usage on future schemas in database ridgeline_analytics to role ridgeline_reporter;
grant select on future tables in database ridgeline_analytics to role ridgeline_reporter;
grant select on future views in database ridgeline_analytics to role ridgeline_reporter;

-- Cortex AI functions (ticket theme classification)
grant database role snowflake.cortex_user to role ridgeline_transformer;
-- let Cortex run in another region if the account's region lacks a model
alter account set cortex_enabled_cross_region = 'ANY_REGION';

-- one service user for the pipeline, key-pair auth only
create user if not exists ridgeline_svc
    type = service
    default_warehouse = ridgeline_wh
    default_role = ridgeline_transformer
    rsa_public_key = '<PUBLIC_KEY>';
grant role ridgeline_loader to user ridgeline_svc;
grant role ridgeline_transformer to user ridgeline_svc;
grant role ridgeline_reporter to user ridgeline_svc;

-- the account identifier to send back (format ORGNAME-ACCOUNTNAME)
select current_organization_name() || '-' || current_account_name() as account_identifier;
