<template>
  <div class="col-md-12">
      <div class="mb-3">
        Items per Page:
        <select v-model="pageSize" @change="handlePageSizeChange($event)">
          <option v-for="size in pageSizes" :key="size" :value="size">
            {{ size }}
          </option>
        </select>
      </div>
      <b-pagination
        v-model="page"
        :total-rows="count"
        :per-page="pageSize"
        size="sm"
        @change="handlePageChange"
      ></b-pagination>
  </div>
</template>

<script>
export default {
  name: "Pagination",
  data() {
    return {
      page: 1,
    };
  },
  methods: {
    handlePageChange(value) {
      this.page = value;
    },
  },
};
</script>
