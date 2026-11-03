targetScope = 'subscription'

@description('Stable role definition ID used by the resource-group infrastructure template.')
param roleDefinitionName string = '3db1392d-2f72-47f3-9453-6860731aa1f0'

resource whatIfOperator 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: roleDefinitionName
  properties: {
    roleName: 'SMS Resource Group What-If Operator'
    description: 'Allows the SMS GitHub deployment identity to inspect deployments and run ARM what-if.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.Resources/deployments/read'
          'Microsoft.Resources/deployments/whatIf/action'
          'Microsoft.Resources/subscriptions/resourceGroups/read'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
    assignableScopes: [
      subscription().id
    ]
  }
}
