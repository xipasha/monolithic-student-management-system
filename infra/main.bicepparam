using './main.bicep'

param location = 'southafricanorth'
param appName = 'sms-student-management-20261103'
param appServicePlanName = 'sikalumbit30_asp_8006'
param postgresServerName = 'sms-student-management-pg-20261103'
param identityName = 'sms-github-deploy'
param websiteContributorAssignmentName = 'e824bd71-5741-44df-9db5-762b334c6be6'
param containerImage = 'ghcr.io/xipasha/monolithic-student-management-system:3de04ed11878d7a91599a3bd222f1106993334d7'
param secretKey = readEnvironmentVariable('SECRET_KEY')
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD', '')
param databaseUrl = readEnvironmentVariable('DATABASE_URL', '')
param adminPassword = readEnvironmentVariable('ADMIN_PASSWORD', '')
param coursesServiceToken = readEnvironmentVariable('COURSES_SERVICE_TOKEN', '')
param coursesServiceDatabaseUrl = readEnvironmentVariable('COURSES_DATABASE_URL', '')
param coursesServiceUrl = readEnvironmentVariable('COURSES_SERVICE_URL', '')
param coursesServiceEnabled = bool(readEnvironmentVariable('COURSES_SERVICE_ENABLED', 'false'))
