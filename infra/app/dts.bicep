param name string
param taskHubName string
param location string = resourceGroup().location
param tags object = {}
param managedIdentityPrincipalId string
param deployerPrincipalId string = ''

@allowed([
  'Consumption'
  'Dedicated'
])
param skuName string = 'Consumption'

@minValue(1)
param dedicatedCapacity int = 1

var durableTaskDataContributorRoleId = '0ad04412-c4d5-4796-b79c-f76d14c8d402'

resource scheduler 'Microsoft.DurableTask/schedulers@2025-11-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    ipAllowlist: [
      '0.0.0.0/0'
    ]
    sku: skuName == 'Dedicated'
      ? {
          name: skuName
          capacity: dedicatedCapacity
        }
      : {
          name: skuName
        }
  }
}

resource taskHub 'Microsoft.DurableTask/schedulers/taskHubs@2025-11-01' = {
  parent: scheduler
  name: taskHubName
}

resource appTaskHubRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(taskHub.id, managedIdentityPrincipalId, durableTaskDataContributorRoleId)
  scope: taskHub
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      durableTaskDataContributorRoleId
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerTaskHubRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(taskHub.id, deployerPrincipalId, durableTaskDataContributorRoleId)
  scope: taskHub
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      durableTaskDataContributorRoleId
    )
    principalId: deployerPrincipalId
  }
}

output name string = scheduler.name
output endpoint string = scheduler.properties.endpoint
output taskHubName string = taskHub.name
output dashboardUrl string = taskHub.properties.dashboardUrl
