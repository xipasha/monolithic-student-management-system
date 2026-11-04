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

@description('Globally unique Azure Service Bus namespace name.')
param serviceBusNamespaceName string = 'sms-student-events-20261104'

@description('Service Bus queue for student lifecycle notifications.')
param serviceBusQueueName string = 'student-notifications'

@description('Globally unique Linux App Service name for the notifications worker.')
param notifierAppName string = '${appName}-notifier'

@description('Worker image name and commit-SHA tag.')
param notifierContainerImage string = 'ghcr.io/xipasha/monolithic-student-management-system-notifier:latest'

@description('Whether the monolith should publish events. Keep false until the worker is healthy.')
param notificationsEnabled bool = false

@description('Container Apps environment for the extracted courses service.')
param coursesEnvironmentName string = 'sms-courses-aca-env'

@description('Log Analytics workspace used by the courses Container Apps environment.')
param coursesWorkspaceName string = 'sms-courses-logs-20261104'

@description('Name of the courses service Container App.')
param coursesContainerAppName string = 'sms-courses-api'

@description('Published public GHCR image for the courses service.')
param coursesContainerImage string = 'ghcr.io/xipasha/monolithic-student-management-system:latest'

@description('Whether to manage the courses Container App resource.')
param manageCoursesService bool = false

@description('Public URL of the courses service used by the monolith.')
param coursesServiceUrl string = ''

@secure()
@description('Shared bearer token used by the monolith and courses service.')
param coursesServiceToken string = ''

@secure()
@description('PostgreSQL connection URL for the isolated courses database role.')
param coursesServiceDatabaseUrl string = ''

@description('Whether the monolith should use the courses service. Keep false until data comparison and cutover.')
param coursesServiceEnabled bool = false

@description('Manage the Service Bus namespace, queue, and queue-scoped role assignments.')
param manageServiceBus bool = true

@secure()
@description('Application signing key. Supply it from a secure environment variable.')
param secretKey string

var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var whatIfRoleId = '3db1392d-2f72-47f3-9453-6860731aa1f0'
var websiteContributorRoleId = 'de139f84-1756-47ae-9be6-808fbbe84772'
var serviceBusDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var serviceBusDataReceiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
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

resource coursesWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: coursesWorkspaceName
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource coursesEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: coursesEnvironmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: coursesWorkspace.properties.customerId
        sharedKey: coursesWorkspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource coursesContainerApp 'Microsoft.App/containerApps@2025-01-01' = if (manageCoursesService) {
  name: coursesContainerAppName
  location: location
  properties: {
    managedEnvironmentId: coursesEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'courses-service-token'
          value: coursesServiceToken
        }
        {
          name: 'courses-database-url'
          value: coursesServiceDatabaseUrl
        }
      ]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8000
        transport: 'auto'
      }
    }
    template: {
      containers: [
        {
          name: 'courses-api'
          image: coursesContainerImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'COURSES_SERVICE_TOKEN'
              secretRef: 'courses-service-token'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'courses-database-url'
            }
            {
              name: 'APP_MODULE'
              value: 'services.courses.app:app'
            }
            {
              name: 'PORT'
              value: '8000'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-requests'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux,container'
  identity: {
    type: 'SystemAssigned'
  }
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

resource notifierWebApp 'Microsoft.Web/sites@2023-12-01' = {
  name: notifierAppName
  location: location
  kind: 'app,linux,container'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: resourceId('Microsoft.Web/serverfarms', appServicePlanName)
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${notifierContainerImage}'
      alwaysOn: true
    }
  }
  dependsOn: createAppServicePlan ? [
    appServicePlan
  ] : []
}

resource notifierWebConfig 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: notifierWebApp
  name: 'web'
  properties: {
    healthCheckPath: '/health'
  }
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2021-11-01' = if (manageServiceBus) {
  name: serviceBusNamespaceName
  location: location
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  properties: {
    disableLocalAuth: true
  }
}

resource notificationQueue 'Microsoft.ServiceBus/namespaces/queues@2021-11-01' = if (manageServiceBus) {
  parent: serviceBusNamespace
  name: serviceBusQueueName
  properties: {
    maxDeliveryCount: 5
    deadLetteringOnMessageExpiration: true
  }
}

resource monolithSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (manageServiceBus) {
  scope: notificationQueue
  name: guid(notificationQueue.id, appName, serviceBusDataSenderRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataSenderRoleId)
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource notifierReceiverRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (manageServiceBus) {
  scope: notificationQueue
  name: guid(notificationQueue.id, notifierAppName, serviceBusDataReceiverRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataReceiverRoleId)
    principalId: notifierWebApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
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
    NOTIFICATIONS_ENABLED: string(notificationsEnabled)
    COURSES_SERVICE_ENABLED: string(coursesServiceEnabled)
    COURSES_SERVICE_URL: coursesServiceUrl
    COURSES_SERVICE_TOKEN: coursesServiceToken
    SERVICEBUS_NAMESPACE: '${serviceBusNamespaceName}.servicebus.windows.net'
    SERVICEBUS_QUEUE: serviceBusQueueName
  }
}

resource notifierAppSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: notifierWebApp
  name: 'appsettings'
  properties: {
    DOCKER_REGISTRY_SERVER_URL: 'https://ghcr.io'
    WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
    WEBSITES_PORT: '8000'
    PORT: '8000'
    SERVICEBUS_NAMESPACE: '${serviceBusNamespaceName}.servicebus.windows.net'
    SERVICEBUS_QUEUE: serviceBusQueueName
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
