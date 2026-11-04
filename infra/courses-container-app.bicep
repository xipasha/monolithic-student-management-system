targetScope = 'resourceGroup'

@description('Azure region for the Container App.')
param location string = 'southafricanorth'

@description('Existing Container Apps managed environment.')
param managedEnvironmentName string = 'sms-courses-aca-env'

@description('Name of the courses Container App.')
param containerAppName string = 'sms-courses-api'

@description('Public GHCR image pinned to a commit SHA.')
param containerImage string

@secure()
@description('Shared bearer token used by the monolith and courses service.')
param coursesServiceToken string

@secure()
@description('PostgreSQL URL for the courses schema.')
param coursesDatabaseUrl string

@minValue(0)
@maxValue(1)
@description('Minimum replicas: set to 1 during cutover, then restore to 0.')
param minReplicas int = 0

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: managedEnvironmentName
}

resource coursesContainerApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'courses-service-token'
          value: coursesServiceToken
        }
        {
          name: 'courses-database-url'
          value: coursesDatabaseUrl
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
          image: containerImage
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
        minReplicas: minReplicas
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
