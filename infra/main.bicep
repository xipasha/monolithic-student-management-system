targetScope = 'resourceGroup'

@description('Azure region for the App Service resources.')
param location string = 'southafricanorth'

@description('Globally unique App Service name.')
param appName string

@description('Linux App Service plan name.')
param appServicePlanName string

@description('PostgreSQL Flexible Server name.')
param postgresServerName string

@description('PostgreSQL database name.')
param postgresDatabaseName string = 'sms'

@description('PostgreSQL administrator login.')
param postgresAdminLogin string = 'smsadmin'

@secure()
@description('PostgreSQL administrator password, supplied from a secure environment variable.')
param postgresAdminPassword string

@secure()
@description('PostgreSQL connection URL (including sslmode=require), supplied from a secure environment variable.')
param databaseUrl string

@description('Initial application administrator username.')
param adminUsername string = 'admin'

@secure()
@description('Initial application administrator password, supplied from a secure environment variable.')
param adminPassword string

@description('Set false for the existing-app CI what-if check.')
param managePostgres bool = true

@description('Set to false when the plan already exists and should only be verified.')
param createAppServicePlan bool = true

@description('User-assigned identity used by GitHub Actions.')
param identityName string

@description('Optional current principal ID for no-drift checks against an existing identity.')
param deploymentIdentityPrincipalId string = ''

@description('Create or manage the GitHub identity and its role assignments.')
param manageDeploymentIdentity bool = true

@description('Role-assignment GUID; use a new GUID for a separate app deployment.')
param websiteContributorAssignmentName string

@description('Published GHCR image name and full commit-SHA tag.')
param containerImage string

@secure()
@description('Application signing key. Supply it from a secure environment variable.')
param secretKey string

var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var whatIfRoleId = '3db1392d-2f72-47f3-9453-6860731aa1f0'
var websiteContributorRoleId = 'de139f84-1756-47ae-9be6-808fbbe84772'
var effectivePrincipalId = empty(deploymentIdentityPrincipalId) ? deploymentIdentity!.properties.principalId : deploymentIdentityPrincipalId

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = if (createAppServicePlan) {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
    size: 'B1'
    family: 'B'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux,container'
  properties: {
    serverFarmId: resourceId('Microsoft.Web/serverfarms', appServicePlanName)
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
    }
  }
  dependsOn: createAppServicePlan ? [
    appServicePlan
  ] : []
}

resource webConfig 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: webApp
  name: 'web'
  properties: {
    healthCheckPath: '/health'
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = if (managePostgres) {
  name: postgresServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    version: '16'
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = if (managePostgres) {
  parent: postgresServer
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource postgresTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = if (managePostgres) {
  parent: postgresServer
  name: 'require_secure_transport'
  properties: {
    value: 'ON'
    source: 'user-override'
  }
}

resource postgresAzureFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (managePostgres) {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource appSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    WEBSITE_HTTPLOGGING_RETENTION_DAYS: '3'
    DOCKER_REGISTRY_SERVER_URL: 'https://ghcr.io'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    WEBSITES_PORT: '8000'
    PORT: '8000'
    SECRET_KEY: secretKey
    DATABASE_URL: databaseUrl
    ADMIN_USERNAME: adminUsername
    ADMIN_PASSWORD: adminPassword
  }
}

resource deploymentIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (manageDeploymentIdentity) {
  name: identityName
  location: location
}

resource githubMainCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (manageDeploymentIdentity) {
  parent: deploymentIdentity
  name: 'github-main'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:xipasha/monolithic-student-management-system:ref:refs/heads/main'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

resource githubMainImmutableCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (manageDeploymentIdentity) {
  parent: deploymentIdentity
  name: 'github-main-immutable-ids'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:xipasha@161585918/monolithic-student-management-system@1436024738:ref:refs/heads/main'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

resource websiteContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (manageDeploymentIdentity) {
  scope: webApp
  name: websiteContributorAssignmentName
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', websiteContributorRoleId)
    principalId: effectivePrincipalId
  }
}

resource ciResourceReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (manageDeploymentIdentity) {
  scope: resourceGroup()
  name: guid(resourceGroup().id, deploymentIdentity.id, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: effectivePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource ciWhatIfAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (manageDeploymentIdentity) {
  scope: resourceGroup()
  name: guid(resourceGroup().id, deploymentIdentity.id, whatIfRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', whatIfRoleId)
    principalId: effectivePrincipalId
    principalType: 'ServicePrincipal'
  }
}
