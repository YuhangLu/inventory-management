<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="candidates.length === 0" class="card empty-state">
      {{ t('restocking.empty') }}
    </div>
    <div v-else>
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
          <span class="budget-readout">{{ money(budget) }}</span>
        </div>
        <div class="budget-control">
          <input
            v-model.number="budget"
            type="range"
            min="0"
            :max="maxBudget"
            step="100"
            class="budget-slider"
            :aria-label="t('restocking.budget')"
          />
          <div class="budget-scale">
            <span>{{ money(0) }}</span>
            <span>{{ t('restocking.maxBudget') }}: {{ money(maxBudget) }}</span>
          </div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.selectedItems') }}</div>
          <div class="stat-value">{{ selectedCount }} / {{ candidates.length }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ money(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ money(remaining) }}</div>
        </div>
      </div>

      <div v-if="orderResult" class="confirmation">
        <span>{{ t('restocking.orderPlaced', { orderNumber: orderResult.order_number }) }}</span>
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ candidates.length }})</h3>
          <button
            class="place-order"
            :disabled="selectedCount === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.name') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.forecast') }}</th>
                <th class="num">{{ t('restocking.table.onHand') }}</th>
                <th class="num">{{ t('restocking.table.restockQty') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineCost') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.selection') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in candidates"
                :key="item.item_sku"
                :class="{ muted: !selectedSkus.has(item.item_sku) }"
              >
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>
                  <span :class="['badge', getTrendClass(item.trend)]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td class="num">{{ item.forecasted_demand.toLocaleString() }}</td>
                <td class="num">{{ item.quantity_on_hand.toLocaleString() }}</td>
                <td class="num">{{ item.restock_quantity.toLocaleString() }}</td>
                <td class="num">{{ money(item.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ money(item.line_cost, 2) }}</strong></td>
                <td class="num">{{ t('orders.submitted.leadTimeDays', { days: item.lead_time_days }) }}</td>
                <td>
                  <span :class="['indicator', { on: selectedSkus.has(item.item_sku) }]">
                    {{ selectedSkus.has(item.item_sku) ? t('restocking.included') : t('restocking.notInBudget') }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const candidates = ref([])
    const maxBudget = ref(0)
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const orderResult = ref(null)

    // Slider works in USD; only display is converted to the current currency
    const money = (amount, decimals = 0) => {
      return decimals > 0
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    // Greedy in priority order: take a whole line if it fits, otherwise skip it and keep going
    const selectedItems = computed(() => {
      let left = budget.value
      const picked = []
      for (const item of candidates.value) {
        if (item.line_cost <= left) {
          picked.push(item)
          left -= item.line_cost
        }
      }
      return picked
    })

    const selectedSkus = computed(() => new Set(selectedItems.value.map(i => i.item_sku)))
    const selectedCount = computed(() => selectedItems.value.length)
    const totalCost = computed(() => selectedItems.value.reduce((sum, i) => sum + i.line_cost, 0))
    const remaining = computed(() => budget.value - totalCost.value)

    const getTrendClass = (trend) => {
      const map = { increasing: 'danger', stable: 'info', decreasing: 'success' }
      return map[trend] || 'info'
    }

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        const data = await api.getRestockRecommendations()
        candidates.value = data.candidates || []
        maxBudget.value = data.max_budget || 0
        budget.value = Math.min(maxBudget.value, Math.round(maxBudget.value * 0.5 / 100) * 100)
      } catch (err) {
        error.value = t('restocking.loadError')
        console.error('Failed to load restock recommendations:', err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (selectedCount.value === 0 || submitting.value) return
      try {
        submitting.value = true
        submitError.value = null
        orderResult.value = null
        const items = selectedItems.value.map(i => ({ sku: i.item_sku, quantity: i.restock_quantity }))
        orderResult.value = await api.createRestockOrder(items)
      } catch (err) {
        submitError.value = t('restocking.submitError')
        console.error('Failed to place restock order:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      loading,
      error,
      candidates,
      maxBudget,
      budget,
      submitting,
      submitError,
      orderResult,
      selectedSkus,
      selectedCount,
      totalCost,
      remaining,
      money,
      getTrendClass,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-readout {
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
}

.budget-control {
  padding: 0.5rem 0;
}

.budget-slider {
  width: 100%;
  cursor: pointer;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.25rem;
  font-size: 0.813rem;
  color: #64748b;
}

.card {
  margin-bottom: 1.5rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.confirmation {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding: 0.75rem 1rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  color: #166534;
}

.confirmation a {
  font-weight: 600;
  color: #0f172a;
}

.place-order {
  padding: 0.5rem 1rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.num {
  text-align: right;
}

tr.muted td {
  opacity: 0.45;
}

.indicator {
  font-size: 0.813rem;
  color: #64748b;
}

.indicator.on {
  color: #166534;
  font-weight: 500;
}
</style>
